from marshmallow import Schema, fields, validate, ValidationError, pre_load
from datetime import datetime

class UserSchema(Schema):
    """Schema for user validation."""
    id = fields.Int(dump_only=True)
    username = fields.Str(required=True, validate=validate.Length(min=3, max=50))
    password = fields.Str(required=True, validate=validate.Length(min=12), load_only=True)
    password_confirmation = fields.Str(required=True, load_only=True)
    role = fields.Str(validate=validate.OneOf(['admin', 'staff']), dump_only=True)
    is_active = fields.Bool(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    last_login_at = fields.DateTime(dump_only=True)

class PatientAdmissionSchema(Schema):
    """Schema for patient admission."""
    chart_number = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    full_name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    phone = fields.Str(allow_none=True, validate=validate.Length(max=20))
    gender = fields.Str(validate=validate.OneOf(['Male', 'Female', 'Other']))
    admission_type = fields.Str(validate=validate.OneOf(['Elective', 'Emergency']))
    surgeon_name = fields.Str(validate=validate.Length(max=100), allow_none=True)
    diagnosis = fields.Str(allow_none=True)
    date_admission = fields.Date(required=True)
    admission_officer = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    disposition_unit = fields.Str(required=True, validate=validate.OneOf(
        ['Ward', 'ICU 1', 'ICU 2', 'ER', 'Day Care Surgery Unit', 'Waiting List']
    ))
    history_done = fields.Str(validate=validate.OneOf(['Yes', 'No']))
    pe_done = fields.Str(validate=validate.OneOf(['Yes', 'No']))
    ix_done = fields.Str(validate=validate.OneOf(['Yes', 'No']))
    pre_anesthesia_done = fields.Str(validate=validate.OneOf(['Yes', 'No']))

class PatientDischargeSchema(Schema):
    """Schema for patient discharge."""
    discharge_status_selector = fields.Str(required=True, validate=validate.OneOf(['Discharged', 'Lost to Follow-up']))
    date_discharge = fields.Date(required=True)
    procedure_done = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    discharge_status = fields.Str(required=True, validate=validate.OneOf(
        ['Improved', 'Same', 'LAMA', 'Down referral', 'Up referral', 'Deteriorated', 'Death']
    ))
    op_note_complete = fields.Str(validate=validate.OneOf(['Yes', 'No']))
    biopsy_status = fields.Str(validate=validate.OneOf(['No', 'Yes', 'Pending']))
    biopsy_appointment_date = fields.Date(allow_none=True)
    appointment_date = fields.Date(allow_none=True)
    discharge_officer = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    lost_to_followup_reason = fields.Str(allow_none=True, validate=validate.Length(max=500))
    high_risk_ssi = fields.Bool()

class FollowupCallSchema(Schema):
    """Schema for follow-up call logging."""
    call_type = fields.Str(required=True, validate=validate.OneOf(['2w', '4w']))
    reachable = fields.Str(required=True, validate=validate.OneOf(['Yes', 'No']))
    general_status_2w = fields.Str(allow_none=True)
    general_condition_4w = fields.Str(allow_none=True)
    hospital_rating_2w = fields.Int(validate=validate.Range(min=1, max=5), allow_none=True)
    ssi_surveillance_2w = fields.Str(validate=validate.OneOf(
        ['No Sign of Infection', 'Clinical Signs', 'Diagnosis by a Clinician']
    ), allow_none=True)
    ssi_surveillance_4w = fields.Str(validate=validate.OneOf(
        ['No Sign of Infection', 'Clinical Signs', 'Diagnosis by a Clinician']
    ), allow_none=True)
    unreachable_reason = fields.Str(allow_none=True)
    unreachable_reason_other = fields.Str(allow_none=True)
