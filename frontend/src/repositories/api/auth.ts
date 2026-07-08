import type { UserResponse } from "../types";
import { apiRequest } from "./client";

export interface Credentials {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export function signup(credentials: Credentials): Promise<UserResponse> {
  return apiRequest<UserResponse>("/auth/signup", { method: "POST", body: credentials, skipAuth: true });
}

export function login(credentials: Credentials): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/auth/login", { method: "POST", body: credentials, skipAuth: true });
}
