import { createClient } from "@supabase/supabase-js";

const projectRef = process.env.REACT_APP_SUPABASE_PROJECT_REF?.trim();
const configuredUrl = process.env.REACT_APP_SUPABASE_URL?.trim();
const anonKey = process.env.REACT_APP_SUPABASE_ANON_KEY?.trim();

export const SUPABASE_URL =
  configuredUrl || (projectRef ? `https://${projectRef}.supabase.co` : "");

export const hasSupabaseConfig = Boolean(SUPABASE_URL && anonKey);

export const supabase = hasSupabaseConfig
  ? createClient(SUPABASE_URL, anonKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    })
  : null;
