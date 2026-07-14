import os

if __name__ == '__main__':
    from app import create_app
    app = create_app()
    
    # Initialize database
    with app.app_context():
        from app.models import GlobalSetting
        
        defaults = {
            'total_er_beds': '10',
            'total_icu_beds': '6',
            'total_ward_beds': '26',
            'total_daycare_beds': '10'
        }
        
        for key, val in defaults.items():
            if not GlobalSetting.query.filter_by(key=key).first():
                GlobalSetting.set_setting(key, val)
    
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=5000)
