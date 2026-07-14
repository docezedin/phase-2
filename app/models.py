from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid

class User(db.Model):
    """User model for authentication."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')  # admin or staff
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    
    __table_args__ = (
        db.UniqueConstraint('role', name='one_admin_account', 
                           postgresql_where=db.text("role='admin'")),
    )

class Patient(db.Model):
    """Patient model for admission/discharge tracking."""
    __tablename__ = 'patients'
    
    chart_number = db.Column(db.String(100), primary_key=True, index=True)
    full_name = db.Column(db.String(200), nullable=False, index=True)
    phone = db.Column(db.String(20))
    gender = db.Column(db.String(20))
    admission_type = db.Column(db.String(50))  # Elective, Emergency
    surgeon_name = db.Column(db.String(100), index=True)
    diagnosis = db.Column(db.Text)
    date_admission = db.Column(db.Date, index=True)
    admission_officer = db.Column(db.String(100))
    
    # Pre-op checklist
    history_done = db.Column(db.String(10), default='No')
    pe_done = db.Column(db.String(10), default='No')
    ix_done = db.Column(db.String(10), default='No')
    pre_anesthesia_done = db.Column(db.String(10), default='No')
    
    # Current status
    disposition_unit = db.Column(db.String(50), index=True)  # Ward, ICU 1, ICU 2, ER, Day Care Surgery Unit, Waiting List
    status = db.Column(db.String(50), default='Admitted', index=True)  # Admitted, Discharged, Lost to Follow-up, Left Waiting List
    file_locked = db.Column(db.Boolean, default=False)
    
    # Discharge info
    lost_to_followup_reason = db.Column(db.Text)
    date_discharge = db.Column(db.Date, index=True)
    procedure_done = db.Column(db.Text)
    discharge_status = db.Column(db.String(50))  # Improved, Same, LAMA, Down referral, Up referral, Deteriorated, Death
    op_note_complete = db.Column(db.String(10), default='No')
    discharge_officer = db.Column(db.String(100))
    
    # Biopsy tracking
    biopsy_status = db.Column(db.String(20), default='No')  # No, Yes, Pending, Delayed
    biopsy_appointment_date = db.Column(db.Date)
    biopsy_final_result = db.Column(db.Text, default='Pending Review')
    biopsy_result_received = db.Column(db.String(10), default='No')
    biopsy_delay_reason = db.Column(db.Text)
    appointment_date = db.Column(db.Date)
    
    # 2-week follow-up
    general_status_2w = db.Column(db.Text)
    deterioration_details = db.Column(db.Text)
    hospital_rating_2w = db.Column(db.Integer)
    ssi_surveillance_2w = db.Column(db.String(100), default='No')
    caller_name_2w = db.Column(db.String(100))
    call_2w_state = db.Column(db.String(20), default='Pending', index=True)  # Pending, Retry, Cleared
    call_2w_retry_date = db.Column(db.Date)
    call_2w_unreachable_reason = db.Column(db.Text)
    
    # 4-week follow-up
    general_condition_4w = db.Column(db.Text)
    service_complaints = db.Column(db.Text)
    physician_opinion = db.Column(db.Text)
    nursing_opinion = db.Column(db.Text)
    price_worthiness = db.Column(db.Text)
    ssi_surveillance_4w = db.Column(db.String(100), default='No')
    caller_name_4w = db.Column(db.String(100))
    call_4w_state = db.Column(db.String(20), default='Pending', index=True)  # Pending, Retry, Cleared
    call_4w_retry_date = db.Column(db.Date)
    call_4w_unreachable_reason = db.Column(db.Text)
    
    # Risk markers
    high_risk_ssi = db.Column(db.Boolean, default=False)
    waiting_list_leave_reason = db.Column(db.Text)
    
    # Relationships
    room_transfers = db.relationship('RoomTransfer', backref='patient', lazy='dynamic', cascade='all, delete-orphan')

class RoomTransfer(db.Model):
    """Room transfer history for patients."""
    __tablename__ = 'room_transfers'
    
    id = db.Column(db.Integer, primary_key=True)
    chart_number = db.Column(db.String(100), db.ForeignKey('patients.chart_number'), nullable=False, index=True)
    room_service = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    days_spent = db.Column(db.Integer, default=0)

class AuditLog(db.Model):
    """Audit log for compliance."""
    __tablename__ = 'audit_log'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(50), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    chart_number = db.Column(db.String(100), index=True)
    details = db.Column(db.Text)

class GlobalSetting(db.Model):
    """Global configuration settings."""
    __tablename__ = 'global_settings'
    
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    
    @classmethod
    def get_setting(cls, key, default=None):
        """Get a setting by key."""
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @classmethod
    def set_setting(cls, key, value):
        """Set a setting by key."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = cls(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
