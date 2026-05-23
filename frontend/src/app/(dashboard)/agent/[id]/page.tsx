'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { agentIdSchema } from '@/lib/validators';
import { useAgentStatus, useAgentDetails, useUpdateAgentSettings } from '@/hooks/useAgent';
import { useAgentMessages } from '@/hooks/useAgentMessages';
import { useAgentActions as useAgentActionsQuery } from '@/hooks/useAgentMessages';
import { useRealtimeFeed, useAgentStatusRealtime } from '@/hooks/useRealtimeFeed';
import { useTelegramSession, useAnalyticsData } from '@/hooks/useTelegramSession';
import { useStartAgent, useStopAgent, useTriggerMessage } from '@/hooks/useAgents';
import { useToast } from '@/components/ui/toast';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import { Card, Skeleton, Spinner, Divider } from '@/components/ui/card';
import { ConfirmDialog, Modal } from '@/components/ui/modal';
import { sanitizeText, maskPhoneNumber } from '@/lib/sanitize';
import {
  agentSettingsSchema, triggerMessageSchema,
  type AgentSettingsValues, type TriggerMessageValues,
} from '@/lib/validators';
import {
  Settings, ScrollText, Zap, MessageSquare, BarChart2, Brain,
  Play, Square, Send, Wifi, WifiOff, AlertTriangle, RefreshCw,
  Bot, Clock, CheckCircle, XCircle, Loader2,
} from 'lucide-react';
import { formatDistanceToNow, format } from 'date-fns';
import { ru } from 'date-fns/locale';
import { cn } from '@/lib/utils';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import type { AgentTab, AgentActivity, AgentMessageRecord, ApiError } from '@/types';

const TABS: { id: AgentTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'settings',  label: 'Настройки',  icon: Settings },
  { id: 'logs',      label: 'Логи',        icon: ScrollText },
  { id: 'actions',   label: 'Управление',  icon: Zap },
  { id: 'telegram',  label: 'Telegram',    icon: MessageSquare },
  { id: 'analytics', label: 'Аналитика',   icon: BarChart2 },
  { id: 'memory',    label: 'Память',      icon: Brain },
];

export default function AgentPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();

  const rawId = params['id'] as string;
  const parsed = agentIdSchema.safeParse(rawId);
  if (!parsed.success) {
    return <div className="p-8 font-mono text-crimson-400">Недопустимый ID агента</div>;
  }
  const agentId = parsed.data;

  const initialTab = (searchParams.get('tab') as AgentTab) ?? 'settings';
  const [activeTab, setActiveTab] = useState<AgentTab>(
    TABS.some(t => t.id === initialTab) ? initialTab : 'settings'
  );

  const handleTabChange = (tab: AgentTab) => {
    setActiveTab(tab);
    router.replace(`/agent/${agentId}?tab=${tab}`, { scroll: false });
  };

  const { data: status } = useAgentStatus(agentId);
  const { data: details } = useAgentDetails(agentId);
  useAgentStatusRealtime(agentId);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="h-10 w-10 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
            <Bot className="h-5 w-5 text-plasma-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-display text-xl font-bold text-void-100">
                {details?.name ?? <Skeleton className="h-6 w-32 inline-block" />}
              </h1>
              {status && <AgentStatusBadge state={status.state} />}
            </div>
            <p className="font-mono text-xs text-void-600 mt-0.5">{agentId}</p>
          </div>
        </div>
        <AgentControls agentId={agentId} state={status?.state} />
      </div>

      {/* Tabs */}
      <div className="border-b border-void-800">
        <div className="flex gap-0 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-3 font-mono text-xs border-b-2 transition-all duration-150 whitespace-nowrap',
                activeTab === tab.id
                  ? 'border-plasma-500 text-plasma-400'
                  : 'border-transparent text-void-500 hover:text-void-300 hover:border-void-700',
              )}
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div>
        {activeTab === 'settings'  && <TabSettings  agentId={agentId} />}
        {activeTab === 'logs'      && <TabLogs       agentId={agentId} />}
        {activeTab === 'actions'   && <TabActions    agentId={agentId} />}
        {activeTab === 'telegram'  && <TabTelegram   agentId={agentId} />}
        {activeTab === 'analytics' && <TabAnalytics  agentId={agentId} />}
        {activeTab === 'memory'    && <TabMemory />}
      </div>
    </div>
  );
}

// ── Agent Controls ────────────────────────────────────────────────────────────
function AgentControls({ agentId, state }: { agentId: string; state?: string }) {
  const { toast } = useToast();
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop,  isPending: stopping } = useStopAgent();
  const [stopConfirm, setStopConfirm] = useState(false);

  return (
    <div className="flex items-center gap-2">
      <Button variant="success" size="sm"
        onClick={() => start(agentId, {
          onSuccess: () => toast('Агент запускается', 'success'),
          onError: (e: unknown) => toast((e as ApiError).message, 'error'),
        })}
        disabled={state === 'running' || state === 'starting'}
        isLoading={starting}
        leftIcon={<Play className="h-3.5 w-3.5" />}
      >
        Запустить
      </Button>

      <Button variant="danger" size="sm"
        onClick={() => setStopConfirm(true)}
        disabled={state !== 'running'}
        isLoading={stopping}
        leftIcon={<Square className="h-3.5 w-3.5" />}
      >
        Стоп
      </Button>

      <ConfirmDialog
        isOpen={stopConfirm}
        onClose={() => setStopConfirm(false)}
        onConfirm={() => {
          setStopConfirm(false);
          stop(agentId, {
            onSuccess: () => toast('Агент остановлен', 'warning'),
            onError: (e: unknown) => toast((e as ApiError).message, 'error'),
          });
        }}
        title="Остановить агента?"
        description="Агент перестанет отвечать на сообщения. Вы сможете перезапустить его в любой момент."
        confirmLabel="Остановить"
        variant="danger"
      />
    </div>
  );
}

// ── Tab: Settings ─────────────────────────────────────────────────────────────
function TabSettings({ agentId }: { agentId: string }) {
  const { toast } = useToast();
  const { data: details, isLoading } = useAgentDetails(agentId);
  const update = useUpdateAgentSettings(agentId);

  const [values, setValues] = useState<AgentSettingsValues>({
    name: '', soul_prompt: '', system_prompt: '',
  });
  const [formErrors, setFormErrors] = useState<Partial<AgentSettingsValues>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (details) {
      setValues({
        name: details.name,
        soul_prompt: details.soul_prompt ?? '',
        system_prompt: details.system_prompt ?? '',
      });
    }
  }, [details]);

  const set = (field: keyof AgentSettingsValues, value: string) => {
    setValues((v) => ({ ...v, [field]: value }));
    setDirty(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = agentSettingsSchema.safeParse(values);
    if (!result.success) {
      const fe: Partial<AgentSettingsValues> = {};
      result.error.issues.forEach(i => { fe[i.path[0] as keyof AgentSettingsValues] = i.message; });
      setFormErrors(fe);
      return;
    }
    setFormErrors({});
    try {
      await update.mutateAsync(result.data);
      toast('Настройки сохранены', 'success');
      setDirty(false);
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Ошибка сохранения', 'error');
    }
  };

  if (isLoading) return <SettingsSkeleton />;

  return (
    <form onSubmit={handleSave} className="max-w-2xl space-y-6">
      <Input
        label="Имя агента"
        value={values.name}
        onChange={(e) => set('name', e.target.value)}
        error={formErrors.name}
      />

      <Textarea
        label="SOUL.md — Характер"
        value={values.soul_prompt}
        onChange={(e) => set('soul_prompt', e.target.value)}
        error={formErrors.soul_prompt}
        className="min-h-[200px]"
        showCount
        maxLength={50000}
        hint="Описание личности, стиля общения и особенностей агента"
      />

      <Textarea
        label="System Prompt"
        value={values.system_prompt}
        onChange={(e) => set('system_prompt', e.target.value)}
        error={formErrors.system_prompt}
        className="min-h-[180px]"
        showCount
        maxLength={20000}
        hint="Базовые инструкции для языковой модели"
      />

      <div className="flex items-center gap-3 pt-2">
        <Button type="submit" isLoading={update.isPending} disabled={!dirty}>
          Сохранить изменения
        </Button>
        {dirty && (
          <span className="font-mono text-xs text-amber-400">● Есть несохранённые изменения</span>
        )}
      </div>
    </form>
  );
}

function SettingsSkeleton() {
  return (
    <div className="max-w-2xl space-y-6">
      {[120, 240, 200].map((h, i) => <Skeleton key={i} style={{ height: h }} />)}
    </div>
  );
}

// ── Tab: Logs ─────────────────────────────────────────────────────────────────
function TabLogs({ agentId }: { agentId: string }) {
  const { data: messages, isLoading: mlLoading } = useAgentMessages(agentId, 50);
  const { data: actions, isLoading: alLoading }  = useAgentActionsQuery(agentId, 50);
  const { feedItems, isConnected } = useRealtimeFeed(agentId);

  const [filter, setFilter] = useState<'all' | 'messages' | 'events' | 'errors'>('all');
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Merge initial + realtime
  const allItems = [
    ...(messages ?? []).map(m => ({
      type: 'message' as const, id: m.id ?? m.created_at,
      timestamp: m.created_at, peer: m.peer, role: m.role,
      content: m.content, direction: m.direction,
    })),
    ...(actions ?? []).map(a => ({
      type: 'event' as const, id: a.id ?? a.created_at,
      timestamp: a.created_at, event_type: a.event_type,
      status: a.status, error: a.error,
    })),
    ...feedItems,
  ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  // Deduplicate by id
  const seen = new Set<string>();
  const deduped = allItems.filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });

  const filtered = deduped.filter(item => {
    if (filter === 'messages' && item.type !== 'message') return false;
    if (filter === 'events'   && item.type !== 'event')   return false;
    if (filter === 'errors'   && !(item.type === 'event' && item.status === 'failed')) return false;
    if (search) {
      const q = search.toLowerCase();
      if (item.type === 'message') return item.content.toLowerCase().includes(q) || item.peer.toLowerCase().includes(q);
      return item.event_type.toLowerCase().includes(q);
    }
    return true;
  });

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [filtered.length, autoScroll]);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <Input
          placeholder="Поиск по содержимому..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:max-w-xs"
        />
        <div className="flex items-center gap-1">
          {(['all', 'messages', 'events', 'errors'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 py-1.5 rounded-sm font-mono text-xs border transition-colors',
                filter === f
                  ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                  : 'border-void-700 text-void-500 hover:text-void-300 hover:border-void-600',
              )}
            >
              {{ all: 'Все', messages: 'Сообщения', events: 'События', errors: 'Ошибки' }[f]}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={() => setAutoScroll(v => !v)}
            className={cn('font-mono text-xs px-3 py-1.5 rounded-sm border transition-colors',
              autoScroll ? 'border-neon-800 text-neon-500' : 'border-void-700 text-void-600')}
          >
            {autoScroll ? '⬇ Авто-скролл' : '— Авто-скролл'}
          </button>
          <div className="flex items-center gap-1.5">
            {isConnected ? <Wifi className="h-3.5 w-3.5 text-neon-400" /> : <WifiOff className="h-3.5 w-3.5 text-void-600" />}
            <span className={cn('font-mono text-[10px]', isConnected ? 'text-neon-500' : 'text-void-600')}>
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </div>

      {/* Log container */}
      <Card variant="glass" padding="none">
        <div className="h-[600px] overflow-y-auto p-2 space-y-0.5 font-mono text-xs">
          {(mlLoading || alLoading) ? (
            <div className="flex items-center justify-center h-full">
              <Spinner />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-void-600 gap-2">
              <ScrollText className="h-8 w-8 opacity-30" />
              <p>Нет записей</p>
            </div>
          ) : (
            filtered.map(item => (
              <LogRow key={item.id} item={item} />
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </Card>

      <p className="font-mono text-xs text-void-600 text-right">
        {filtered.length} записей
      </p>
    </div>
  );
}

function LogRow({ item }: { item: ReturnType<typeof [].map>[number] & { type: string } }) {
  const time = format(new Date((item as { timestamp: string }).timestamp), 'HH:mm:ss');

  if ((item as { type: string }).type === 'message') {
    const m = item as { peer: string; role: string; content: string; direction?: string };
    const isIn = m.direction === 'incoming' || m.role === 'user';
    return (
      <div className={cn(
        'flex gap-3 px-3 py-1.5 rounded-[2px] hover:bg-void-800/40',
        isIn ? 'border-l-2 border-plasma-800' : 'border-l-2 border-neon-900',
      )}>
        <span className="text-void-600 w-16 shrink-0 tabular-nums">{time}</span>
        <span className={cn('w-8 shrink-0 uppercase text-[10px]', isIn ? 'text-plasma-600' : 'text-neon-700')}>
          {isIn ? '←IN' : '→OUT'}
        </span>
        <span className="text-void-500 shrink-0 max-w-[100px] truncate">{m.peer}</span>
        <span className="text-void-300 flex-1">{sanitizeText(m.content)}</span>
      </div>
    );
  }

  const e = item as { event_type: string; status: string; error: string | null };
  const statusColor: Record<string, string> = {
    succeeded: 'text-neon-600', failed: 'text-crimson-500',
    running: 'text-plasma-500', pending: 'text-void-500', cancelled: 'text-void-600',
  };
  return (
    <div className="flex gap-3 px-3 py-1.5 rounded-[2px] hover:bg-void-800/40 border-l-2 border-void-800">
      <span className="text-void-600 w-16 shrink-0 tabular-nums">{time}</span>
      <span className="text-void-700 w-8 shrink-0">EVT</span>
      <span className={cn('w-20 shrink-0', statusColor[e.status] ?? 'text-void-500')}>
        [{e.status.toUpperCase()}]
      </span>
      <span className="text-void-400 flex-1">{e.event_type}</span>
      {e.error && <span className="text-crimson-500 truncate max-w-[150px]">{e.error}</span>}
    </div>
  );
}

// ── Tab: Actions ──────────────────────────────────────────────────────────────
function TabActions({ agentId }: { agentId: string }) {
  const { toast } = useToast();
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop,  isPending: stopping }  = useStopAgent();
  const trigger = useTriggerMessage(agentId);
  const [stopConfirm, setStopConfirm] = useState(false);
  const [triggerModal, setTriggerModal] = useState(false);
  const [triggerValues, setTriggerValues] = useState<TriggerMessageValues>({ peer: '', text: '' });
  const [triggerErrors, setTriggerErrors] = useState<Partial<TriggerMessageValues>>({});
  const [triggerResult, setTriggerResult] = useState<string | null>(null);

  const handleTrigger = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = triggerMessageSchema.safeParse(triggerValues);
    if (!result.success) {
      const fe: Partial<TriggerMessageValues> = {};
      result.error.issues.forEach(i => { fe[i.path[0] as keyof TriggerMessageValues] = i.message; });
      setTriggerErrors(fe);
      return;
    }
    setTriggerErrors({});
    try {
      const res = await trigger.mutateAsync(result.data);
      setTriggerResult(res.sent ? '✓ Отправлено' : `✗ ${res.error ?? 'Ошибка'}`);
      toast(res.sent ? 'Сообщение отправлено' : (res.error ?? 'Ошибка'), res.sent ? 'success' : 'error');
    } catch (e: unknown) {
      toast((e as ApiError).message, 'error');
    }
  };

  const actions = [
    {
      title: 'Запустить агента',
      desc: 'Агент начнёт получать и отвечать на сообщения в Telegram',
      icon: Play,
      color: 'text-neon-400',
      bg: 'bg-neon-950/40 border-neon-900',
      action: () => start(agentId, {
        onSuccess: () => toast('Агент запускается', 'success'),
        onError: (e: unknown) => toast((e as ApiError).message, 'error'),
      }),
      loading: starting,
      label: 'Запустить',
      variant: 'success' as const,
      destructive: false,
    },
    {
      title: 'Остановить агента',
      desc: 'Агент перестанет обрабатывать входящие сообщения',
      icon: Square,
      color: 'text-crimson-400',
      bg: 'bg-crimson-950/40 border-crimson-900',
      action: () => setStopConfirm(true),
      loading: stopping,
      label: 'Остановить',
      variant: 'danger' as const,
      destructive: true,
    },
    {
      title: 'Отправить сообщение',
      desc: 'Принудительно отправить сообщение конкретному пользователю',
      icon: Send,
      color: 'text-plasma-400',
      bg: 'bg-plasma-950/40 border-plasma-900',
      action: () => { setTriggerResult(null); setTriggerModal(true); },
      loading: false,
      label: 'Отправить',
      variant: 'default' as const,
      destructive: false,
    },
  ];

  return (
    <div className="max-w-2xl space-y-4">
      {actions.map((a) => (
        <Card key={a.title} variant="glass" padding="md" className={cn('flex items-center justify-between gap-4 border', a.bg)}>
          <div className="flex items-start gap-4">
            <div className={cn('h-9 w-9 rounded-sm flex items-center justify-center shrink-0 bg-void-800')}>
              <a.icon className={cn('h-4 w-4', a.color)} />
            </div>
            <div>
              <p className="font-mono text-sm font-medium text-void-200">{a.title}</p>
              <p className="font-mono text-xs text-void-500 mt-0.5">{a.desc}</p>
            </div>
          </div>
          <Button variant={a.variant} size="sm" onClick={a.action} isLoading={a.loading} className="shrink-0">
            {a.label}
          </Button>
        </Card>
      ))}

      <ConfirmDialog
        isOpen={stopConfirm}
        onClose={() => setStopConfirm(false)}
        onConfirm={() => {
          setStopConfirm(false);
          stop(agentId, {
            onSuccess: () => toast('Агент остановлен', 'warning'),
            onError: (e: unknown) => toast((e as ApiError).message, 'error'),
          });
        }}
        title="Остановить агента?"
        description="Агент перестанет отвечать. Можно перезапустить в любой момент."
        confirmLabel="Остановить"
        variant="danger"
      />

      <Modal isOpen={triggerModal} onClose={() => setTriggerModal(false)} title="Отправить сообщение" size="md">
        <form onSubmit={handleTrigger} className="space-y-4">
          <Input
            label="Получатель (peer)"
            placeholder="@username или +79991234567"
            value={triggerValues.peer}
            onChange={(e) => setTriggerValues(v => ({ ...v, peer: e.target.value }))}
            error={triggerErrors.peer}
          />
          <Textarea
            label="Текст сообщения"
            placeholder="Введите текст..."
            value={triggerValues.text}
            onChange={(e) => setTriggerValues(v => ({ ...v, text: e.target.value }))}
            error={triggerErrors.text}
            maxLength={4096}
            showCount
          />
          {triggerResult && (
            <p className={cn('font-mono text-sm', triggerResult.startsWith('✓') ? 'text-neon-400' : 'text-crimson-400')}>
              {triggerResult}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setTriggerModal(false)}>
              Отмена
            </Button>
            <Button type="submit" size="sm" isLoading={trigger.isPending}
              leftIcon={<Send className="h-3.5 w-3.5" />}>
              Отправить
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

// ── Tab: Telegram ─────────────────────────────────────────────────────────────
function TabTelegram({ agentId }: { agentId: string }) {
  const { data: session, isLoading } = useTelegramSession(agentId);

  if (isLoading) return <Spinner className="mt-8" />;
  if (!session) return (
    <div className="font-mono text-sm text-void-500 mt-8">
      Telegram сессия не найдена
    </div>
  );

  const statusColors: Record<string, string> = {
    authorized:       'text-neon-400',
    code_requested:   'text-plasma-400',
    password_required:'text-amber-400',
    not_started:      'text-void-500',
    error:            'text-crimson-400',
    revoked:          'text-crimson-500',
  };

  const rows = [
    { label: 'Статус авторизации', value: session.authorization_status.toUpperCase(), color: statusColors[session.authorization_status] },
    { label: 'Номер телефона',      value: maskPhoneNumber(session.phone_number) },
    { label: 'API ID',              value: session.api_id ? String(session.api_id) : '—' },
    {
      label: 'Последняя авторизация',
      value: session.last_authorized_at
        ? formatDistanceToNow(new Date(session.last_authorized_at), { addSuffix: true, locale: ru })
        : '—',
    },
    { label: 'Последняя ошибка', value: session.last_error ?? '—', color: session.last_error ? 'text-crimson-400' : undefined },
  ];

  return (
    <div className="max-w-xl space-y-4">
      <Card variant="glass" padding="none">
        {rows.map((row, i) => (
          <div key={row.label} className={cn(
            'flex items-start justify-between px-5 py-4',
            i < rows.length - 1 && 'border-b border-void-800',
          )}>
            <span className="font-mono text-xs text-void-500 uppercase tracking-wider">{row.label}</span>
            <span className={cn('font-mono text-sm text-right', row.color ?? 'text-void-200')}>
              {row.value}
            </span>
          </div>
        ))}
      </Card>

      {(session.authorization_status === 'error' || session.authorization_status === 'revoked') && (
        <div className="p-4 rounded-sm bg-amber-950/20 border border-amber-900/50 flex items-center justify-between gap-4">
          <div>
            <p className="font-mono text-sm text-amber-400 font-medium">Требуется переподключение</p>
            <p className="font-mono text-xs text-amber-600 mt-0.5">
              Сессия истекла или была отозвана
            </p>
          </div>
          <Button variant="outline" size="sm" leftIcon={<RefreshCw className="h-3.5 w-3.5" />}>
            Переподключить
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Tab: Analytics ────────────────────────────────────────────────────────────
function TabAnalytics({ agentId }: { agentId: string }) {
  const [days, setDays] = useState<7 | 30>(7);
  const { data, isLoading } = useAnalyticsData(agentId, days);

  const tooltipStyle = {
    backgroundColor: '#1a1a28',
    border: '1px solid rgba(96, 96, 117, 0.2)',
    borderRadius: '2px',
    fontFamily: 'var(--font-geist-mono)',
    fontSize: '11px',
    color: '#c0c0cc',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        {([7, 30] as const).map(d => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={cn(
              'px-4 py-1.5 rounded-sm font-mono text-xs border transition-colors',
              days === d
                ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                : 'border-void-700 text-void-500 hover:text-void-300',
            )}
          >
            {d} дней
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card variant="glass" padding="md">
            <h3 className="font-mono text-xs text-void-400 uppercase tracking-wider mb-4">
              Сообщения по дням
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={data}>
                <defs>
                  <linearGradient id="msgGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#1a7fff" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#1a7fff" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(96,96,117,0.1)" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} />
                <YAxis tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="messages" stroke="#1a7fff" fill="url(#msgGrad)" strokeWidth={1.5} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          <Card variant="glass" padding="md">
            <h3 className="font-mono text-xs text-void-400 uppercase tracking-wider mb-4">
              Ошибки по дням
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(96,96,117,0.1)" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} />
                <YAxis tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="errors" fill="#f43f5e" opacity={0.8} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>
      )}
    </div>
  );
}

// ── Tab: Memory (stub) ────────────────────────────────────────────────────────
function TabMemory() {
  return (
    <div className="max-w-xl">
      <Card variant="glass" padding="lg" className="text-center space-y-4">
        <Brain className="h-12 w-12 text-void-700 mx-auto" />
        <h3 className="font-display text-lg font-bold text-void-400">
          Memory API недоступен
        </h3>
        <p className="font-mono text-sm text-void-600 leading-relaxed">
          Для подключения Mem0 памяти необходим эндпоинт{' '}
          <code className="text-plasma-500 bg-plasma-950/40 px-1 py-0.5 rounded-[2px]">
            /api/v1/agents/{'{id}'}/memory
          </code>{' '}
          на бэкенде. После добавления эндпоинта — подключить здесь.
        </p>
      </Card>
    </div>
  );
}
