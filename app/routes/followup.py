from flask import Blueprint, request, redirect, url_for, flash, g, current_app
from app import db, limiter
from app.models import Patient
from app.decorators import login_required, csrf_protect
from app.schemas import FollowupCallSchema
from app.utils import log_audit, parse_date
from datetime import datetime, timedelta
from marshmallow import ValidationError

followup_bp = Blueprint('followup', __name__, url_prefix='/followup')
schema = FollowupCallSchema()

VALID_BIOPSY_STATUSES = {'No', 'Yes', 'Pending', 'Delayed'}

@followup_bp.route('/log-call', methods=['POST'])
@login_required
@csrf_protect
@limiter.limit("30 per minute")
def log_call(chart_number=None):
    """Log 2-week or 4-week follow-up call."""
    chart = request.form.get('chart_number', '').strip()
    
    try:
        data = schema.load(request.form)
        call_type = data['call_type']
        reachable = data['reachable']
        
        patient = Patient.query.filter_by(chart_number=chart).first()
        if not patient:
            raise ValueError("Patient record does not exist.")
        if patient.file_locked:
            raise ValueError("This patient file is locked. An administrator must unlock it before editing.")
        if patient.status != 'Discharged':
            raise ValueError("This action is only available for discharged records.")
        if patient.discharge_status == 'Death':
            raise ValueError("Follow-up calls cannot be recorded for deceased patients.")
        
        retry_dt = (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        if reachable == 'No':
            unreachable_reason = request.form.get('unreachable_reason', '').strip()
            if unreachable_reason not in ['Phone not working/Switched off', 'Patient or attendant not available', 
                                           'Language barrier Structural issue', 'Other']:
                raise ValueError("Invalid unreachable reason.")
            
            other_text = request.form.get('unreachable_reason_other', '').strip()
            if unreachable_reason == 'Other' and not other_text:
                raise ValueError("Please provide detailed reason.")
            
            final_reason = f"Other: {other_text}" if unreachable_reason == 'Other' else unreachable_reason
            
            if call_type == '2w':
                patient.call_2w_state = 'Retry'
                patient.call_2w_retry_date = parse_date(retry_dt, "Retry date")
                patient.call_2w_unreachable_reason = final_reason
                patient.general_status_2w = 'Not Available'
                patient.ssi_surveillance_2w = 'Not Available'
            else:
                patient.call_4w_state = 'Retry'
                patient.call_4w_retry_date = parse_date(retry_dt, "Retry date")
                patient.call_4w_unreachable_reason = final_reason
                patient.general_condition_4w = 'Not Available'
                patient.ssi_surveillance_4w = 'Not Available'
            
            log_audit(f"{call_type}_followup_retry", chart, f"retry_date={retry_dt}; reason={final_reason}")
            flash(f"Patient unreachable. Follow-up retry due on {retry_dt}.", "warning")
        
        elif call_type == '2w':
            rating = request.form.get('hospital_rating_2w', '')
            try:
                rating = int(rating)
            except ValueError:
                raise ValueError("Rating must be a number from 1 to 5.")
            if rating not in range(1, 6):
                raise ValueError("Rating must be from 1 to 5.")
            
            ssi_status = request.form.get('ssi_surveillance_2w', '').strip()
            if ssi_status not in ['No Sign of Infection', 'Clinical Signs', 'Diagnosis by a Clinician']:
                raise ValueError("Invalid SSI status.")
            
            patient.general_status_2w = request.form.get('general_status_2w', '').strip()
            patient.deterioration_details = request.form.get('deterioration_details', '').strip()
            patient.hospital_rating_2w = rating
            patient.ssi_surveillance_2w = ssi_status
            patient.caller_name_2w = request.form.get('caller_name_2w', '').strip()
            patient.call_2w_state = 'Cleared'
            patient.call_2w_retry_date = None
            patient.call_2w_unreachable_reason = None
            
            log_audit('2w_followup_completed', chart)
            flash("2-week verification record saved.", "success")
        
        else:  # 4w
            ssi_status = request.form.get('ssi_surveillance_4w', '').strip()
            if ssi_status not in ['No Sign of Infection', 'Clinical Signs', 'Diagnosis by a Clinician']:
                raise ValueError("Invalid SSI status.")
            
            patient.general_condition_4w = request.form.get('general_condition_4w', '').strip()
            patient.service_complaints = request.form.get('service_complaints', '').strip()
            patient.physician_opinion = request.form.get('physician_opinion', '').strip()
            patient.nursing_opinion = request.form.get('nursing_opinion', '').strip()
            patient.price_worthiness = request.form.get('price_worthiness', '').strip()
            patient.ssi_surveillance_4w = ssi_status
            patient.caller_name_4w = request.form.get('caller_name_4w', '').strip()
            patient.call_4w_state = 'Cleared'
            patient.call_4w_retry_date = None
            patient.call_4w_unreachable_reason = None
            patient.file_locked = True
            
            log_audit('4w_followup_completed_and_locked', chart)
            flash("4-week quality audit finalized and record locked.", "success")
        
        db.session.commit()
    
    except ValidationError as err:
        db.session.rollback()
        flash(f"Validation error: {err.messages}", "danger")
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Followup call error: {str(e)}")
        flash("An error occurred during followup call logging.", "danger")
    
    return redirect(url_for('patients.profile', chart_number=chart))

@followup_bp.route('/update-biopsy', methods=['POST'])
@login_required
@csrf_protect
@limiter.limit("30 per minute")
def update_biopsy():
    """Update biopsy status."""
    chart = request.form.get('biopsy_chart_number', '').strip()
    
    try:
        patient = Patient.query.filter_by(chart_number=chart).first()
        if not patient:
            raise ValueError("Patient record does not exist.")
        if patient.file_locked:
            raise ValueError("This patient file is locked. An administrator must unlock it before editing.")
        
        status_selection = request.form.get('biopsy_status', '').strip()
        if status_selection not in VALID_BIOPSY_STATUSES:
            raise ValueError("Invalid biopsy status.")
        
        result_text = request.form.get('biopsy_final_result', '').strip()
        if not result_text or len(result_text) > 5000:
            raise ValueError("Biopsy result must be between 1 and 5000 characters.")
        
        received = request.form.get('biopsy_result_received', 'No').strip()
        if received not in ['Yes', 'No']:
            raise ValueError("Invalid biopsy received status.")
        
        delay_reason = request.form.get('biopsy_delay_reason', '').strip()
        if status_selection == 'Delayed':
            if not delay_reason:
                raise ValueError('Please provide biopsy delay reason.')
            received = 'No'
        else:
            delay_reason = ''
        
        patient.biopsy_status = status_selection
        patient.biopsy_final_result = result_text
        patient.biopsy_result_received = received
        patient.biopsy_delay_reason = delay_reason
        
        db.session.commit()
        log_audit('biopsy_status_updated', chart, f"status={status_selection}; received={received}")
        flash('Biopsy status updated.', 'success')
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Biopsy update error: {str(e)}")
        flash("An error occurred during biopsy update.", "danger")
    
    return redirect(url_for('patients.profile', chart_number=chart))
