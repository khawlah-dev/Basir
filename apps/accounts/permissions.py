from rest_framework.permissions import BasePermission

from apps.accounts.models import User


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN


class IsTeacher(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.TEACHER


class IsLeaderOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in [User.Role.LEADER, User.Role.ADMIN]


class IsTeacherLeaderOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in [
            User.Role.TEACHER,
            User.Role.LEADER,
            User.Role.ADMIN,
        ]


def can_access_teacher(*, user, teacher) -> bool:
    if user.role == User.Role.ADMIN:
        return True
    if user.role == User.Role.LEADER:
        return bool(user.school_id and user.school_id == teacher.school_id)
    if user.role == User.Role.TEACHER:
        return teacher.user_id == user.id
    return False
