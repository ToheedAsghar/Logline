/**
 * Centralized UI text strings and error messages for Authentication screens
 * (Login, Signup, Forgot Password, Reset Password, Email Verification, Google SSO).
 */

export const AUTH_STRINGS = {
  // Common UI labels
  WORK_EMAIL_LABEL: "Work email",
  PASSWORD_LABEL: "Password",
  NEW_PASSWORD_LABEL: "New password",
  CONFIRM_PASSWORD_LABEL: "Confirm new password",
  NAME_LABEL: "Name",

  // Headers & Subtitles
  SIGN_IN_TITLE: "Sign in to Logline",
  SIGN_IN_SUBTITLE: "Pick up right where your timeline left off.",
  SIGN_UP_TITLE: "Create your account",
  SIGN_UP_SUBTITLE: "Turn your GitHub, calendar and chat signals into logs and standups.",
  FORGOT_PASSWORD_TITLE: "Forgot your password?",
  FORGOT_PASSWORD_SUBTITLE: "Enter your work email and we'll send you a link to reset your password.",
  RESET_PASSWORD_TITLE: "Set a new password",
  RESET_PASSWORD_SUBTITLE: "Enter your new password below to update your account.",
  VERIFY_EMAIL_TITLE: "Email verification",
  VERIFY_EMAIL_SUBTITLE: "Verifying your email address with Logline...",
  OAUTH_CALLBACK_TITLE: "Signing you in...",
  OAUTH_CALLBACK_SUBTITLE: "Authenticating with Google OAuth...",

  // Buttons
  SIGN_IN_BTN: "Sign in",
  SIGN_IN_WORKING: "Logging in…",
  CREATE_ACCOUNT_BTN: "Create account",
  CREATE_ACCOUNT_WORKING: "Creating account…",
  SEND_RESET_LINK_BTN: "Send reset link",
  SEND_RESET_LINK_WORKING: "Sending link…",
  RESET_PASSWORD_BTN: "Reset password",
  RESET_PASSWORD_WORKING: "Resetting password…",
  CONTINUE_TO_SIGN_IN: "Continue to Sign in",
  RESEND_VERIFICATION_BTN: "Resend verification email",
  RESEND_VERIFICATION_WORKING: "Resending email…",

  // Placeholders
  EMAIL_PLACEHOLDER: "you@company.dev",
  PASSWORD_PLACEHOLDER: "••••••••",
  NAME_PLACEHOLDER: "Jane Doe",

  // Messages & Notifications
  FORGOT_PASSWORD_GENERIC_SUCCESS:
    "If an account exists for that email, a password reset link has been sent. Please check your inbox.",
  RESET_PASSWORD_SUCCESS:
    "Your password has been reset successfully! You can now sign in with your new password.",
  VERIFY_EMAIL_SUCCESS:
    "Your email address has been verified successfully! You can now sign in to your account.",
  SIGNUP_SUCCESS_VERIFY_PROMPT:
    "Account created! We've sent a verification email to your address. Please verify your email before signing in.",
  UNVERIFIED_EMAIL_NOTICE:
    "Your email address has not been verified yet. Please check your inbox or resend the verification link.",
  RESEND_VERIFICATION_SENT:
    "If an account exists for that email and needs verification, a new email has been sent.",

  // Error Messages
  GOOGLE_SSO_FAILED: "Google sign-in failed or was cancelled. Please try again.",
  VERIFY_EMAIL_FAILED: "Invalid or expired verification link.",
  TOKEN_MISSING_OR_INVALID: "Invalid or expired link. Please request a new link.",
  PASSWORD_MISMATCH: "Passwords do not match. Please make sure both fields match.",
  PASSWORD_LENGTH_ERROR: "Password must be between 8 and 128 characters long.",
  DEFAULT_LOGIN_ERROR: "Couldn't log in — please check your credentials and try again.",
  DEFAULT_SIGNUP_ERROR: "Couldn't create an account — try again.",
} as const;
