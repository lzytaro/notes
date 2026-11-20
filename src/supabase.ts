import { createClient, type AuthChangeEvent, type Session, type SupabaseClient, type User } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
const runtimeOrigin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5173/'
const redirectUrl = (import.meta.env.VITE_SUPABASE_REDIRECT_URL as string | undefined) || runtimeOrigin

export const supabase: SupabaseClient | null = url && anonKey ? createClient(url, anonKey) : null
export const supabaseConfigured = Boolean(supabase)

export async function getCurrentUser() {
  if (!supabase) return null
  const { data } = await supabase.auth.getUser()
  return data.user
}

export function onAuthChange(callback: (event: AuthChangeEvent, session: Session | null) => void) {
  if (!supabase) return () => {}
  const { data } = supabase.auth.onAuthStateChange(callback)
  return () => data.subscription.unsubscribe()
}

export async function sendMagicLink(email: string) {
  if (!supabase) return new Error('尚未配置 Supabase')
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: redirectUrl },
  })
  return error
}

export async function signInWithGoogle() {
  if (!supabase) return new Error('尚未配置 Supabase')
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: redirectUrl },
  })
  return error
}

export async function signOutUser() {
  if (!supabase) return null
  const { error } = await supabase.auth.signOut()
  return error
}

export type { User }
