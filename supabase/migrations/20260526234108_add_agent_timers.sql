CREATE TABLE public.agent_timers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
    peer TEXT NOT NULL,
    trigger_at TIMESTAMP WITH TIME ZONE NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT agent_timers_status_check CHECK (status IN ('pending', 'running', 'succeeded', 'failed'))
);

CREATE INDEX agent_timers_agent_id_status_trigger_at_idx 
ON public.agent_timers(agent_id, status, trigger_at);

ALTER TABLE public.agent_timers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their agent timers"
ON public.agent_timers
FOR ALL
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.agents
        WHERE agents.id = agent_timers.agent_id
            AND agents.owner_id = auth.uid()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.agents
        WHERE agents.id = agent_timers.agent_id
            AND agents.owner_id = auth.uid()
    )
);
