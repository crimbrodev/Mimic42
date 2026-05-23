'use client';

import { createBrowserClient } from '@supabase/ssr';
import type { Database } from '@/types/supabase';

let client: ReturnType<typeof createBrowserClient<Database>> | null = null;

/**
 * Returns a singleton Supabase browser client.
 * Safe to call multiple times — returns same instance.
 */
export function getSupabaseClient() {
  if (client) return client;

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error(
      'Missing Supabase environment variables: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are required.'
    );
  }

  client = createBrowserClient<Database>(supabaseUrl, supabaseAnonKey);
  return client;
}

export type SupabaseBrowserClient = ReturnType<typeof getSupabaseClient>;
