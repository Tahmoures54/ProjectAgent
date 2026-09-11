# Path: pms_app/blueprints/__init__.py
from __future__ import annotations

"""
این پکیج فقط برای گروه‌بندی blueprintهاست.

ثبت (register) شدن blueprintها در pms_app/__init__.py (create_app) انجام می‌شود.
برای ساده‌تر شدن create_app، یک helper هم اینجا گذاشته‌ایم که لیست blueprintها را برگرداند.

نکته:
- این importها داخل تابع انجام می‌شوند تا احتمال circular import کمتر شود.
"""

from typing import List
from flask import Blueprint


def get_blueprints() -> List[Blueprint]:
    """
    لیست blueprintهای پروژه را برای register شدن برمی‌گرداند.

    در create_app می‌توانید بنویسید:
        from pms_app.blueprints import get_blueprints
        for bp in get_blueprints():
            app.register_blueprint(bp)
    """
    from pms_app.blueprints.auth import bp as auth_bp
    from pms_app.blueprints.contracts import bp as contracts_bp
    from pms_app.blueprints.items import bp as items_bp
    from pms_app.blueprints.main import bp as main_bp
    from pms_app.blueprints.projects import bp as projects_bp
    from pms_app.blueprints.reports import bp as reports_bp
    from pms_app.blueprints.users import bp as users_bp
    from pms_app.blueprints.billing import bp as billing_bp
    from pms_app.blueprints.daily_reports import bp as daily_reports_bp
    from pms_app.blueprints.concerns import bp as concerns_bp

    return [
        main_bp,
        auth_bp,
        users_bp,
        projects_bp,
        contracts_bp,
        items_bp,
        reports_bp,
        billing_bp,
        daily_reports_bp,
        concerns_bp,
    ]


__all__ = ["get_blueprints"]