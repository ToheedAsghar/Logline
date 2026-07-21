PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Error Messages
TEXT_UNAUTHORIZED = "Could not validate credentials"

# Email Verification
EMAIL_VERIFICATION_SALT = "email-verification"

# Password Reset
PASSWORD_RESET_SALT = "password-reset"
TEXT_PASSWORD_RESET_SUBJECT = "Reset your Logline password"

# password verification
EMAIL_VERIFICATION_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24  # 24 hours
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60

# Login
TEXT_LOGIN_INVALID_CREDENTIALS = "Invalid email or password"
TEXT_LOGIN_EMAIL_NOT_VERIFIED = "Email not verified. Please check your inbox for a verification link"

# Google SSO
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
GOOGLE_SCOPES = ["openid", "email", "profile"]
GOOGLE_LOGIN_STATE_PURPOSE = "google_login"
TEXT_GOOGLE_MISSING_ID_TOKEN = "Google's token response did not include an id_token"
TEXT_GOOGLE_EMAIL_NOT_VERIFIED = "Google account email is not verified"
TEXT_GOOGLE_MISSING_EMAIL_CLAIM = "Google ID token did not include an email claim"

# Password Reset
TEXT_PASSWORD_TOKEN_ERROR = "Invalid or expired reset link"
TEXT_FORGOT_PASSWORD_GENERIC_MESSAGE = "If that email exists, a password reset link has been sent."
TEXT_PASSWORD_RESET_SUCCESSFULL = "Password has been reset successfully"
FORGOT_PASSWORD_WAIT_MESSAGE = "A password reset email was already sent recently. Please wait before requesting another."
PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS = 60 * 60  # 1 hour
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = 60
