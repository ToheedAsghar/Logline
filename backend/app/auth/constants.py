PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Error Messages
TEXT_UNAUTHORIZED = "Could not validate credentials"

# Email Verification
EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24  # 24 hours
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60

# Login
TEXT_LOGIN_INVALID_CREDENTIALS = "Invalid email or password"
TEXT_LOGIN_EMAIL_NOT_VERIFIED = "Email not verified. Please check your inbox for a verification link"
TEXT_INACTIVE_USER_ACCOUNT = "Inactive user account"

# Google SSO
GOOGLE_LOGIN_STATE_PURPOSE = "google_login"
TEXT_GOOGLE_SIGN_IN_FAILED = "Google sign-in could not be completed"

# Registration & Password Reset
TEXT_SIGNUP_GENERIC_MESSAGE = (
    "If this email isn't already registered, we've sent a verification link to it. Please check your inbox."
)
TEXT_PASSWORD_TOKEN_ERROR = "Invalid or expired reset link"
TEXT_FORGOT_PASSWORD_GENERIC_MESSAGE = "If that email exists, a password reset link has been sent."
TEXT_PASSWORD_RESET_SUCCESSFULL = "Password has been reset successfully"
PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS = 60 * 60  # 1 hour
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = 60
