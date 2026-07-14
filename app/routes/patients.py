from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app
from app import db, limiter
from app.models import Patient, RoomTransfer, GlobalSetting
from app.decorators import login_required, csrf_protect
from app.schemas import PatientAdmissionSchema, PatientDischargeSchema
from app.utils import log_audit, parse_date
from datetime import datetime
from marshmallow import ValidationError

patients_bp = Blueprint('patients', __name__, url_prefix='/patients')
admission_schema = PatientAdmissionSchema()
discharge_schema = PatientDischargeSchema()

VALID_UNITS = {'Ward', 'ICU 1', 'ICU 2', 'ER', 'Day Care Surgery Unit', 'Waiting List'}
ACTIVE_UNITS = VALID_UNITS - {'Waiting List'}
VALID_DISCHARGE_OUTCOMES = {'Improved', 'Same', 'LAMA', 'Down referral', 'Up referral', 'Deteriorated', 'Death'}

def get_bed_capacity(unit):
    """Get bed capacity for a unit."""
    capacity_map = {
        'Ward': 'total_ward_beds',
        'ICU 1': 'total_icu_beds',
        'ICU 2': 'total_icu_beds',
        'ER': 'total_er_beds',
        'Day Care Surgery Unit': 'total_daycare_beds',
    }
    capacity_key = capacity_map.get(unit)
    if not capacity_key:
        return 0
    try:
        value = GlobalSetting.get_setting(capacity_key, '0')
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0

def get_occupied_beds(unit, exclude_chart_number=None):
    """Get occupied beds for a unit."""
    query = Patient.query.filter_by(status='Admitted')
    
    if unit in {'ICU 1', 'ICU 2'}:
        query = query.filter(Patient.disposition_unit.in_(['ICU 1', 'ICU 2']))
    else:
        query = query.filter_by(disposition_unit=unit)
    
    if exclude_chart_number:
        query = query.filter(Patient.chart_number != exclude_chart_number)
    
    return query.count()

def ensure_unit_capacity(unit, exclude_chart_number=None):
    """Ensure bed capacity is available."""
    capacity = get_bed_capacity(unit)
    occupied = get_occupied_beds(unit, exclude_chart_number)
    
    if occupied >= capacity:
        raise ValueError(f"No {unit} bed is available. Place the patient on the waiting list or choose another unit.")

@patients_bp.route('/admit', methods=['POST'])
@login_required
@csrf_protect
@limiter.limit("30 per minute")
def admit():
    """Admit patient or add to waiting list."""
    try:
        # Validate input
        data = admission_schema.load(request.form)
        
        chart_num = data['chart_number'].strip()
        disp_unit = data['disposition_unit']
        admission_date = data['date_admission']
        
        status = 'Waiting List' if disp_unit == 'Waiting List' else 'Admitted'
        existing = Patient.query.filter_by(chart_number=chart_num).first()
        
        if existing:
            if existing.file_locked:
                raise ValueError('This patient file is locked. An administrator must unlock it before editing.')
            if existing.status != 'Waiting List' or status != 'Admitted':
                raise ValueError('This chart number already exists.')
            
            if disp_unit != 'Waiting List':
                ensure_unit_capacity(disp_unit, exclude_chart_number=chart_num)
            
            existing.disposition_unit = disp_unit
            existing.status = 'Admitted'
            existing.date_admission = admission_date
            existing.admission_officer = data['admission_officer']
            existing.waiting_list_leave_reason = None
            action = 'waiting_list_patient_admitted'
        else:
            if status == 'Admitted':
                ensure_unit_capacity(disp_unit)
            
            patient = Patient(
                chart_number=chart_num,
                full_name=data['full_name'],
                phone=data.get('phone', '').strip(),
                gender=data.get('gender'),
                admission_type=data.get('admission_type'),
                surgeon_name=data.get('surgeon_name', '').strip(),
                diagnosis=data.get('diagnosis', '').strip(),
                date_admission=admission_date,
                admission_officer=data['admission_officer'],
                history_done=data.get('history_done', 'No'),
                pe_done=data.get('pe_done', 'No'),
                ix_done=data.get('ix_done', 'No'),
                pre_anesthesia_done=data.get('pre_anesthesia_done', 'No'),
                disposition_unit=disp_unit,
                status=status
            )
            db.session.add(patient)
            action = 'patient_admitted' if status == 'Admitted' else 'patient_added_to_waiting_list'
        
        # Create room transfer if admitted
        if status == 'Admitted':
            if existing:
                RoomTransfer.query.filter_by(chart_number=chart_num).delete()
            room_transfer = RoomTransfer(
                chart_number=chart_num,
                room_service=disp_unit,
                start_date=admission_date
            )
            db.session.add(room_transfer)
        
        db.session.commit()
        log_audit(action, chart_num, f"unit={disp_unit}")
        flash(f"Admission registry updated for chart {chart_num}.", "success")
    
    except ValidationError as err:
        flash(f"Validation error: {err.messages}", "danger")
    except ValueError as err:
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admission error: {str(e)}")
        flash("An error occurred during admission.", "danger")
    
    return redirect(url_for('dashboard.index'))

@patients_bp.route('/<chart_number>', methods=['GET'])
@login_required
def profile(chart_number):
    """View patient profile."""
    patient = Patient.query.filter_by(chart_number=chart_number).first()
    if not patient:
        flash("Patient profile does not exist.", "danger")
        return redirect(url_for('dashboard.index'))
    
    transfers = RoomTransfer.query.filter_by(chart_number=chart_number).order_by(RoomTransfer.id).all()
    return render_template('patients/profile.html', patient=patient, transfers=transfers, today_str=datetime.today().strftime("%Y-%m-%d"))

@patients_bp.route('/<chart_number>/discharge', methods=['POST'])
@login_required
@csrf_protect
@limiter.limit("30 per minute")
def discharge(chart_number):
    """Discharge patient."""
    try:
        data = discharge_schema.load(request.form)
        patient = Patient.query.filter_by(chart_number=chart_number).first()
        
        if not patient:
            raise ValueError("Patient record does not exist.")
        if patient.file_locked:
            raise ValueError("This patient file is locked. An administrator must unlock it before editing.")
        if patient.status != 'Admitted':
            raise ValueError("This action is only available for admitted records.")
        
        discharge_date = data['date_discharge']
        admission_date = parse_date(patient.date_admission.isoformat(), "Admission date")
        if discharge_date < admission_date:
            raise ValueError('Discharge date cannot be before admission date.')
        
        status_type = data['discharge_status_selector']
        if status_type == 'Lost to Follow-up':
            patient.lost_to_followup_reason = data.get('lost_to_followup_reason', '')
        
        patient.date_discharge = discharge_date
        patient.procedure_done = data['procedure_done']
        patient.discharge_status = data['discharge_status']
        patient.op_note_complete = data.get('op_note_complete', 'No')
        patient.biopsy_status = data.get('biopsy_status', 'No')
        patient.biopsy_appointment_date = data.get('biopsy_appointment_date')
        patient.appointment_date = data.get('appointment_date')
        patient.discharge_officer = data['discharge_officer']
        patient.status = status_type
        patient.high_risk_ssi = data.get('high_risk_ssi', False)
        patient.call_2w_state = 'Pending'
        patient.call_4w_state = 'Pending'
        
        # Update room transfer
        active_trans = RoomTransfer.query.filter_by(chart_number=chart_number, end_date=None).first()
        if active_trans:
            transfer_start = parse_date(active_trans.start_date.isoformat(), 'Current room start date')
            if discharge_date < transfer_start:
                raise ValueError('Discharge date cannot be before current room start date.')
            active_trans.end_date = discharge_date
            active_trans.days_spent = (discharge_date - transfer_start).days
        
        db.session.commit()
        log_audit('patient_discharged', chart_number, f"status={status_type}; outcome={data['discharge_status']}")
        flash('Discharge record saved.', 'success')
    
    except ValidationError as err:
        db.session.rollback()
        flash(f"Validation error: {err.messages}", "danger")
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Discharge error: {str(e)}")
        flash("An error occurred during discharge.", "danger")
    
    return redirect(url_for('patients.profile', chart_number=chart_number))

@patients_bp.route('/<chart_number>/change-room', methods=['POST'])
@login_required
@csrf_protect
@limiter.limit("30 per minute")
def change_room(chart_number):
    """Change patient room allocation."""
    try:
        new_unit = request.form.get('new_disposition_unit')
        if new_unit not in ACTIVE_UNITS:
            raise ValueError("Invalid destination unit.")
        
        change_date = parse_date(request.form.get('change_date'), "Reallocation date")
        patient = Patient.query.filter_by(chart_number=chart_number).first()
        
        if not patient:
            raise ValueError("Patient record does not exist.")
        if patient.file_locked:
            raise ValueError("This patient file is locked. An administrator must unlock it before editing.")
        if patient.status != 'Admitted':
            raise ValueError("This action is only available for admitted records.")
        
        ensure_unit_capacity(new_unit, exclude_chart_number=chart_number)
        
        admission_date = parse_date(patient.date_admission.isoformat(), "Admission date")
        if change_date < admission_date:
            raise ValueError("Reallocation date cannot be before admission date.")
        
        active_trans = RoomTransfer.query.filter_by(chart_number=chart_number, end_date=None).first()
        if active_trans:
            start_date = parse_date(active_trans.start_date.isoformat(), "Current room start date")
            if change_date < start_date:
                raise ValueError("Reallocation date cannot be before current room start date.")
            days = (change_date - start_date).days
            active_trans.end_date = change_date
            active_trans.days_spent = days
        
        new_trans = RoomTransfer(
            chart_number=chart_number,
            room_service=new_unit,
            start_date=change_date
        )
        patient.disposition_unit = new_unit
        db.session.add(new_trans)
        db.session.commit()
        
        log_audit('room_changed', chart_number, f"unit={new_unit}; date={change_date.isoformat()}")
        flash(f"Room allocation updated to: {new_unit}", "info")
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Room change error: {str(e)}")
        flash("An error occurred during room reallocation.", "danger")
    
    return redirect(url_for('patients.profile', chart_number=chart_number))
