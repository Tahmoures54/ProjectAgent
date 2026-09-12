# Path: pms_app/utils/access.py
"""
Tenant-safe resource lookup.

Every HTTP handler that loads a project, contract, or item by id should go
through these helpers so company isolation and project membership stay in
one place instead of being reimplemented (or forgotten) in each blueprint.
"""
from __future__ import annotations

from typing import Optional

from flask import abort
from flask_login import current_user
from sqlalchemy.orm import Query

from pms_app.extensions import db
from pms_app.models.contract import Contract
from pms_app.models.daily_report import DailyReport
from pms_app.models.item import ContractItem
from pms_app.models.project import Project
from pms_app.models.project_membership import ProjectMembership

PROJECT_MANAGER_ROLES = ("admin", "manager")


def current_company_id(user=None) -> Optional[int]:
    user = user if user is not None else current_user
    cid = getattr(user, "company_id", None)
    try:
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None


def user_can_access_project(user, project: Optional[Project]) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    checker = getattr(user, "can_access_project", None)
    if not callable(checker):
        return False
    return bool(checker(project))


def user_manages_project(user, project_id: Optional[int]) -> bool:
    """True if the user is an active project admin/manager (not a company-wide role)."""
    if not user or not getattr(user, "is_authenticated", False) or not project_id:
        return False
    membership = ProjectMembership.query.filter_by(
        project_id=int(project_id),
        user_id=user.id,
        status="active",
    ).first()
    role = (getattr(membership, "role", None) or "").strip().lower()
    return bool(membership and role in PROJECT_MANAGER_ROLES)


def get_project_or_403(project_id: int, *, user=None) -> Project:
    user = user if user is not None else current_user
    project = db.session.get(Project, int(project_id))
    if not project:
        abort(404)
    if not user_can_access_project(user, project):
        abort(403)
    return project


def get_contract_or_403(contract_id: int, *, user=None) -> Contract:
    user = user if user is not None else current_user
    contract = db.session.get(Contract, int(contract_id))
    if not contract:
        abort(404)
    project = contract.project
    if project is None:
        abort(404)
    if contract.company_id and project.company_id and int(contract.company_id) != int(project.company_id):
        abort(404)
    if not user_can_access_project(user, project):
        abort(403)
    return contract


def get_item_or_403(item_id: int, *, user=None) -> ContractItem:
    user = user if user is not None else current_user
    item = db.session.get(ContractItem, int(item_id))
    if not item:
        abort(404)
    contract = item.contract
    if contract is None:
        abort(404)
    project = contract.project
    if project is None:
        abort(404)
    if item.company_id and contract.company_id and int(item.company_id) != int(contract.company_id):
        abort(404)
    if not user_can_access_project(user, project):
        abort(403)
    return item


def scope_projects_query(base_query: Query, *, user=None) -> Query:
    user = user if user is not None else current_user
    if getattr(user, "is_owner", False):
        return base_query
    cid = current_company_id(user)
    if cid is None:
        abort(403)
    base_query = base_query.filter(Project.company_id == cid)
    if getattr(user, "is_company_admin", False):
        return base_query
    return (
        base_query.join(ProjectMembership)
        .filter(ProjectMembership.user_id == user.id)
        .filter(ProjectMembership.status == "active")
    )


def scope_daily_reports_query(base_query: Query, *, user=None) -> Query:
    user = user if user is not None else current_user
    if getattr(user, "is_owner", False):
        return base_query
    cid = current_company_id(user)
    if cid is None:
        abort(403)
    base_query = base_query.filter(DailyReport.company_id == cid)
    if getattr(user, "is_company_admin", False):
        return base_query
    return (
        base_query.join(ProjectMembership, ProjectMembership.project_id == DailyReport.project_id)
        .filter(ProjectMembership.user_id == user.id)
        .filter(ProjectMembership.status == "active")
    )
