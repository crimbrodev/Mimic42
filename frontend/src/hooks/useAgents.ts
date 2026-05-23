'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import type { AgentRecord } from '@/types';

/**
 * Hook for fetching the list of all agents for the current user.
 */
export function useAgents() {
  return useQuery({
    queryKey: queryKeys.agents.list(),
    queryFn: agentsApi.list,
    staleTime: 15_000,
  });
}

/**
 * Hook for starting an agent.
 * Optimistically updates state, rolls back on error.
 */
export function useStartAgent() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: agentsApi.start,
    onMutate: async (agentId: string) => {
      // Cancel in-flight queries
      await qc.cancelQueries({ queryKey: queryKeys.agents.detail(agentId) });

      // Snapshot previous value
      const previous = qc.getQueryData(queryKeys.agents.detail(agentId));

      // Optimistically update to 'starting'
      qc.setQueryData(queryKeys.agents.detail(agentId), (old: AgentRecord | undefined) =>
        old ? { ...old, state: 'starting' as const } : old
      );

      return { previous };
    },
    onError: (_, agentId, context) => {
      // Roll back on error
      if (context?.previous) {
        qc.setQueryData(queryKeys.agents.detail(agentId), context.previous);
      }
    },
    onSettled: (_, __, agentId) => {
      // Always refetch after mutation settles
      qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) });
      qc.invalidateQueries({ queryKey: queryKeys.agents.list() });
    },
  });
}

/**
 * Hook for stopping an agent.
 * Optimistically updates state, rolls back on error.
 */
export function useStopAgent() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: agentsApi.stop,
    onMutate: async (agentId: string) => {
      await qc.cancelQueries({ queryKey: queryKeys.agents.detail(agentId) });

      const previous = qc.getQueryData(queryKeys.agents.detail(agentId));

      qc.setQueryData(queryKeys.agents.detail(agentId), (old: AgentRecord | undefined) =>
        old ? { ...old, state: 'stopping' as const } : old
      );

      return { previous };
    },
    onError: (_, agentId, context) => {
      if (context?.previous) {
        qc.setQueryData(queryKeys.agents.detail(agentId), context.previous);
      }
    },
    onSettled: (_, __, agentId) => {
      qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) });
      qc.invalidateQueries({ queryKey: queryKeys.agents.list() });
    },
  });
}

/**
 * Hook for triggering a message to a peer via the agent.
 */
export function useTriggerMessage(agentId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (body: { peer: string; text: string }) =>
      agentsApi.triggerMessage(agentId, body),
    onSuccess: () => {
      // Invalidate messages so they refresh
      qc.invalidateQueries({ queryKey: queryKeys.messages.byAgent(agentId) });
    },
  });
}
