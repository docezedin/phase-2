from flask import Blueprint, render_template, g, current_app
from app import db, limiter
from app.models import Patient, GlobalSetting, AuditLog
from app.decorators import login_required
from datetime import datetime
from sqlalchemy import and_

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/')

@dashboard_bp.route('/', methods=['GET'])
@dashboard_bp.route('/dashboard', methods=['GET'])
@login_required
@limiter.limit("60 per minute")
def index():
    """Dashboard home page."""
    try:
        # Get filter parameters
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        # Get all patients
        patients = Patient.query.all()
        
        # Get bed capacities
        capacities = {}
        for key in ['total_icu_beds', 'total_ward_beds', 'total_er_beds', 'total_daycare_beds']:
            try:
                capacities[key] = max(0, int(GlobalSetting.get_setting(key, '0')))
            except (TypeError, ValueError):
                capacities[key] = 0
        
        # Categorize patients
        active_in_patients = [p for p in patients if p.status == 'Admitted']
        waiting_list_patients = [p for p in patients if p.status == 'Waiting List']
        tracked_out_patients = [p for p in patients if p.status in ['Discharged', 'Lost to Follow-up', 'Left Waiting List']]
        surgeons = list(set(p.surgeon_name for p in patients if p.surgeon_name))
        
        # Calculate occupancy
        icu_occupied = sum(1 for p in active_in_patients if p.disposition_unit in ['ICU 1', 'ICU 2'])
        ward_occupied = sum(1 for p in active_in_patients if p.disposition_unit == 'Ward')
        er_occupied = sum(1 for p in active_in_patients if p.disposition_unit == 'ER')
        daycare_occupied = sum(1 for p in active_in_patients if p.disposition_unit == 'Day Care Surgery Unit')
        
        today = datetime.today()
        today_str = today.strftime("%Y-%m-%d")
        
        # Calculate follow-up alerts and metrics
        alert_2w_list, retry_2w_list, missed_2w_list = [], [], []
        alert_4w_list, retry_4w_list, missed_4w_list = [], [], []
        biopsy_alert_list, biopsy_delayed_list = [], []
        
        total_ssi_cases = 0
        total_tracked_followups = 0
        total_discharged_patients = 0
        total_op_notes_completed = 0
        los_icu_accum, los_icu_count = 0, 0
        los_ward_accum, los_ward_count = 0, 0
        
        for p in patients:
            p.length_of_stay = 0
            p.biopsy_overdue = 'No'
            
            if p.date_admission:
                try:
                    end_d = datetime.strptime(p.date_discharge.isoformat(), "%Y-%m-%d") if p.date_discharge else today
                    adm_d = datetime.strptime(p.date_admission.isoformat(), "%Y-%m-%d")
                    p.length_of_stay = (end_d - adm_d).days
                    
                    if p.status in ['Discharged', 'Lost to Follow-up']:
                        if p.disposition_unit in ['ICU 1', 'ICU 2']:
                            los_icu_accum += p.length_of_stay
                            los_icu_count += 1
                        else:
                            los_ward_accum += p.length_of_stay
                            los_ward_count += 1
                except (TypeError, ValueError):
                    pass
            
            # Biopsy alerts
            if p.status == 'Discharged' and p.biopsy_status in ['Yes', 'Pending', 'Delayed'] and p.biopsy_result_received != 'Yes':
                if p.biopsy_appointment_date and today_str > p.biopsy_appointment_date.isoformat():
                    p.biopsy_overdue = 'Yes'
                if p.biopsy_status == 'Delayed':
                    biopsy_delayed_list.append(p)
                else:
                    biopsy_alert_list.append(p)
            
            # Follow-up alerts
            if p.status == 'Discharged' and p.discharge_status != 'Death':
                try:
                    dis_d = datetime.strptime(p.date_discharge.isoformat(), "%Y-%m-%d")
                    days_since_discharge = (today - dis_d).days
                    
                    if p.call_2w_state == 'Pending' and days_since_discharge >= 14:
                        alert_2w_list.append(p)
                    elif p.call_2w_state == 'Retry' and p.call_2w_retry_date:
                        if today_str >= p.call_2w_retry_date.isoformat():
                            retry_2w_list.append(p)
                        else:
                            missed_2w_list.append(p)
                    
                    if p.call_4w_state == 'Pending' and days_since_discharge >= 28:
                        alert_4w_list.append(p)
                    elif p.call_4w_state == 'Retry' and p.call_4w_retry_date:
                        if today_str >= p.call_4w_retry_date.isoformat():
                            retry_4w_list.append(p)
                        else:
                            missed_4w_list.append(p)
                except (TypeError, ValueError):
                    pass
                
                # Date filtering
                in_range = True
                if start_date and p.date_discharge and p.date_discharge.isoformat() < start_date:
                    in_range = False
                if end_date and p.date_discharge and p.date_discharge.isoformat() > end_date:
                    in_range = False
                
                if in_range:
                    total_discharged_patients += 1
                    if p.op_note_complete == 'Yes':
                        total_op_notes_completed += 1
                    if p.general_status_2w or p.general_condition_4w:
                        total_tracked_followups += 1
                        if p.ssi_surveillance_2w in ['Clinical Signs', 'Diagnosis by a Clinician'] or p.ssi_surveillance_4w in ['Clinical Signs', 'Diagnosis by a Clinician']:
                            total_ssi_cases += 1
        
        # Calculate metrics
        ssi_rate = round((total_ssi_cases / total_tracked_followups) * 100, 1) if total_tracked_followups > 0 else 0.0
        avg_los_icu = round(los_icu_accum / los_icu_count, 1) if los_icu_count > 0 else 0.0
        avg_los_ward = round(los_ward_accum / los_ward_count, 1) if los_ward_count > 0 else 0.0
        op_note_completion_rate = round((total_op_notes_completed / total_discharged_patients) * 100, 1) if total_discharged_patients > 0 else 0.0
        
        totals = {
            'ward_max': capacities['total_ward_beds'],
            'ward_avail': max(0, capacities['total_ward_beds'] - ward_occupied),
            'icu_max': capacities['total_icu_beds'],
            'icu_avail': max(0, capacities['total_icu_beds'] - icu_occupied),
            'er_max': capacities['total_er_beds'],
            'er_avail': max(0, capacities['total_er_beds'] - er_occupied),
            'daycare_max': capacities['total_daycare_beds'],
            'daycare_avail': max(0, capacities['total_daycare_beds'] - daycare_occupied),
            'alert_2w_cnt': len(alert_2w_list) + len(retry_2w_list),
            'alert_4w_cnt': len(alert_4w_list) + len(retry_4w_list),
            'missed_2w_cnt': len(missed_2w_list),
            'missed_4w_cnt': len(missed_4w_list),
            'biopsy_alerts': len(biopsy_alert_list),
            'biopsy_delayed_cnt': len(biopsy_delayed_list),
            'ssi_rate': ssi_rate,
            'avg_los_icu': avg_los_icu,
            'avg_los_ward': avg_los_ward,
            'op_note_rate': op_note_completion_rate,
            'total_audited': total_tracked_followups
        }
        
        return render_template(
            'dashboard/index.html',
            patients=patients,
            active_in_patients=active_in_patients,
            tracked_out_patients=tracked_out_patients,
            waiting_list_patients=waiting_list_patients,
            surgeons=surgeons,
            totals=totals,
            today_str=today_str,
            alert_2w_list=alert_2w_list,
            retry_2w_list=retry_2w_list,
            missed_2w_list=missed_2w_list,
            alert_4w_list=alert_4w_list,
            retry_4w_list=retry_4w_list,
            missed_4w_list=missed_4w_list,
            biopsy_alert_list=biopsy_alert_list,
            biopsy_delayed_list=biopsy_delayed_list,
            start_date=start_date,
            end_date=end_date
        )
    
    except Exception as e:
        current_app.logger.error(f"Dashboard error: {str(e)}", exc_info=True)
        return render_template('error.html', error="An error occurred loading the dashboard."), 500

from flask import request
