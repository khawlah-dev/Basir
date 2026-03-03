from rest_framework.throttling import UserRateThrottle


class WriteUserThrottle(UserRateThrottle):
    scope = "writes"


class SensitiveActionThrottle(UserRateThrottle):
    scope = "sensitive"
