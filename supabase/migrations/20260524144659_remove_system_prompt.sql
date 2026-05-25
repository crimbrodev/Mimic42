-- Remove system_prompt column from agents and agent_onboarding_sessions
ALTER TABLE public.agents DROP COLUMN IF EXISTS system_prompt;
ALTER TABLE public.agent_onboarding_sessions DROP COLUMN IF EXISTS system_prompt;
