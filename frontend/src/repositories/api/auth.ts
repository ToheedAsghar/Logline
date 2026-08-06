import type { UserResponse } from "../types";
import { apiRequest } from "./client";

export interface Credentials {
  email: string;
  password: string;
}

export interface SignupPayload extends Credentials {
  name?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface ForgotPasswordPayload {
  email: string;
}

export interface ResetPasswordPayload {
  token: string;
  new_password: string;
}

export interface ResendVerificationPayload {
  email: string;
}

export interface MessageResponse {
  message: string;
}

export function signup(payload: SignupPayload): Promise<UserResponse> {
  return apiRequest<UserResponse>("/auth/signup", { method: "POST", body: payload, skipAuth: true });
}

export function login(credentials: Credentials): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/auth/login", { method: "POST", body: credentials, skipAuth: true });
}

export function me(): Promise<UserResponse> {
  return apiRequest<UserResponse>("/auth/me");
}

export function forgotPassword(payload: ForgotPasswordPayload): Promise<MessageResponse> {
  return apiRequest<MessageResponse>("/auth/forgot-password", { method: "POST", body: payload, skipAuth: true });
}

export function resetPassword(payload: ResetPasswordPayload): Promise<MessageResponse> {
  return apiRequest<MessageResponse>("/auth/reset-password", { method: "POST", body: payload, skipAuth: true });
}

export function verifyEmail(token: string): Promise<MessageResponse> {
  return apiRequest<MessageResponse>("/auth/verify-email", { query: { token }, skipAuth: true });
}

export function resendVerification(payload: ResendVerificationPayload): Promise<MessageResponse> {
  return apiRequest<MessageResponse>("/auth/resend-verification", { method: "POST", body: payload, skipAuth: true });
}

export function getGoogleLoginUrl(): string {
  const baseUrl: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  return `${baseUrl}/auth/google/login`;
}

export function googleExchange(code: string): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/auth/google/exchange", { method: "POST", body: { code }, skipAuth: true });
}
