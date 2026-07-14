from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app
from app import db, limiter
from app.models import User, GlobalSetting, AuditLog, Patient
from app.decorators import admin_required, csrf_protect, login_required
from app.schemas import UserSchema
from app.utils import log_audit
from werkzeug.security import generate_password_hash
from datetime import datetime
from marshmallow import ValidationError
import re

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
schema = UserSchema()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
PASSWORD_HASH_METHOD = "pbkdf2:sha256"

@admin_bp.route('/users', methods=['GET'])
@admin_required
def manage_users():
    """Manage user accounts."""
    users = User.query.order_by(User.role.desc(), User.username).all()
    audit_entries = AuditLog.query.order_by(AuditLog.id.desc()).limit(100).all()
    return render_template('admin/users.html', users=users, audit_entries=audit_entries)

@admin_bp.route('/users', methods=['POST'])
@admin_required
@csrf_protect
@limiter.limit("10 per minute")
def create_user():
    """Create new staff account."""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    password_confirmation = request.form.get('password_confirmation', '')
    
    try:
        if not USERNAME_RE.fullmatch(username):
            raise ValueError("Username must be 3–50 alphanumeric characters.")
        if len(password) < 12:
            raise ValueError("Staff password must be at least 12 characters.")
        if password != password_confirmation:
            raise ValueError("Password confirmation does not match.")
        
        new_user = User(
            username=username,
            password_hash=generate_password_hash(password, method=PASSWORD_HASH_METHOD),
            role='staff',
            created_at=datetime.utcnow(),
            created_by=g.current_user['id']
        )
        db.session.add(new_user)
        db.session.commit()
        
        log_audit('staff_account_created', details=f"username={username}")
        flash(f"Staff account '{username}' created.", "success")
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create user error: {str(e)}")
        flash("An error occurred creating user account.", "danger")
    
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/users/<int:user_id>/password', methods=['POST'])
@admin_required
@csrf_protect
@limiter.limit("10 per minute")
def reset_user_password(user_id):
    """Reset staff password."""
    password = request.form.get('password', '')
    password_confirmation = request.form.get('password_confirmation', '')
    
    try:
        if len(password) < 12:
            raise ValueError("New password must be at least 12 characters.")
        if password != password_confirmation:
            raise ValueError("Password confirmation does not match.")
        
        user = User.query.get(user_id)
        if not user or user.role != 'staff':
            raise ValueError("Only staff passwords can be reset here.")
        
        user.password_hash = generate_password_hash(password, method=PASSWORD_HASH_METHOD)
        db.session.commit()
        
        log_audit('staff_password_reset', details=f"username={user.username}")
        flash(f"Password reset for '{user.username}'.", "success")
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Password reset error: {str(e)}")
        flash("An error occurred resetting password.", "danger")
    
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
@csrf_protect
@limiter.limit("10 per minute")
def toggle_user_active(user_id):
    """Enable/disable staff account."""
    try:
        user = User.query.get(user_id)
        if not user or user.role != 'staff':
            raise ValueError("Only staff accounts can be modified here.")
        
        user.is_active = not user.is_active
        db.session.commit()
        
        status = 'enabled' if user.is_active else 'disabled'
        log_audit(f'staff_account_{status}', details=f"username={user.username}")
        flash(f"Staff account '{user.username}' {status}.", "info")
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Toggle user error: {str(e)}")
        flash("An error occurred toggling user status.", "danger")
    
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/bed-config', methods=['POST'])
@admin_required
@csrf_protect
@limiter.limit("10 per minute")
def update_bed_capacities():
    """Update hospital bed capacities."""
    try:
        capacities = {}
        for key in ['total_er_beds', 'total_icu_beds', 'total_ward_beds', 'total_daycare_beds']:
            raw_value = request.form.get(key, '')
            try:
                value = int(raw_value)
            except ValueError:
                raise ValueError('Bed capacities must be whole numbers.')
            if not 0 <= value <= 10000:
                raise ValueError('Bed capacities must be between 0 and 10,000.')
            capacities[key] = value
        
        # Verify occupied beds don't exceed new capacity
        occupied = {
            'total_er_beds': Patient.query.filter_by(status='Admitted', disposition_unit='ER').count(),
            'total_icu_beds': Patient.query.filter(Patient.status == 'Admitted', Patient.disposition_unit.in_(['ICU 1', 'ICU 2'])).count(),
            'total_ward_beds': Patient.query.filter_by(status='Admitted', disposition_unit='Ward').count(),
            'total_daycare_beds': Patient.query.filter_by(status='Admitted', disposition_unit='Day Care Surgery Unit').count(),
        }
        
        for key, value in capacities.items():
            if value < occupied[key]:
                raise ValueError(f"Capacity cannot be lower than current occupancy ({occupied[key]}).")
            GlobalSetting.set_setting(key, str(value))
        
        log_audit('bed_capacities_updated', details=str(capacities))
        flash('Bed capacities updated.', 'info')
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Bed config error: {str(e)}")
        flash("An error occurred updating bed capacities.", "danger")
    
    return redirect(url_for('dashboard.index'))

@admin_bp.route('/unlock/<chart_number>', methods=['POST'])
@admin_required
@csrf_protect
@limiter.limit("10 per minute")
def unlock_patient_file(chart_number):
    """Unlock patient file for re-editing."""
    try:
        patient = Patient.query.filter_by(chart_number=chart_number).first()
        if not patient:
            raise ValueError("Patient record does not exist.")
        
        patient.file_locked = False
        db.session.commit()
        
        log_audit('patient_file_unlocked', chart_number)
        flash("File unlocked for re-editing.", "warning")
    
    except ValueError as err:
        db.session.rollback()
        flash(str(err), "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unlock file error: {str(e)}")
        flash("An error occurred unlocking file.", "danger")
    
    return redirect(url_for('patients.profile', chart_number=chart_number))
