import { describe, it, expect } from 'vitest';
import {
  agentIdSchema, phoneNumberSchema, loginSchema,
  telegramCredentialsSchema, agentSettingsSchema,
} from '@/lib/validators';

describe('agentIdSchema — path traversal protection', () => {
  it('accepts valid UUIDs', () => {
    expect(agentIdSchema.safeParse('abc123-def').success).toBe(true);
    expect(agentIdSchema.safeParse('agent_1').success).toBe(true);
    expect(agentIdSchema.safeParse('ABCDEF123').success).toBe(true);
  });

  it('rejects path traversal attempts', () => {
    expect(agentIdSchema.safeParse('../etc/passwd').success).toBe(false);
    expect(agentIdSchema.safeParse('../../secret').success).toBe(false);
    expect(agentIdSchema.safeParse('agent/../../').success).toBe(false);
  });

  it('rejects XSS in agent ID', () => {
    expect(agentIdSchema.safeParse('<script>alert(1)</script>').success).toBe(false);
    expect(agentIdSchema.safeParse('agent<img onerror=1>').success).toBe(false);
    expect(agentIdSchema.safeParse('id"onmouseover="alert').success).toBe(false);
  });

  it('rejects null bytes and special chars', () => {
    expect(agentIdSchema.safeParse('agent\x00id').success).toBe(false);
    expect(agentIdSchema.safeParse('agent id').success).toBe(false);
    expect(agentIdSchema.safeParse('agent;ls').success).toBe(false);
  });

  it('rejects empty string', () => {
    expect(agentIdSchema.safeParse('').success).toBe(false);
  });

  it('rejects overly long IDs', () => {
    expect(agentIdSchema.safeParse('a'.repeat(65)).success).toBe(false);
  });
});

describe('phoneNumberSchema', () => {
  it('accepts valid E.164 numbers', () => {
    expect(phoneNumberSchema.safeParse('+79991234567').success).toBe(true);
    expect(phoneNumberSchema.safeParse('+12125551234').success).toBe(true);
    expect(phoneNumberSchema.safeParse('+44207946001').success).toBe(true);
  });

  it('rejects numbers without country code', () => {
    expect(phoneNumberSchema.safeParse('79991234567').success).toBe(false);
    expect(phoneNumberSchema.safeParse('9991234567').success).toBe(false);
  });

  it('rejects invalid formats', () => {
    expect(phoneNumberSchema.safeParse('+0123456789').success).toBe(false);
    expect(phoneNumberSchema.safeParse('+abc').success).toBe(false);
    expect(phoneNumberSchema.safeParse('').success).toBe(false);
  });

  it('rejects too short / too long', () => {
    expect(phoneNumberSchema.safeParse('+1234').success).toBe(false);
    expect(phoneNumberSchema.safeParse(`+${'1'.repeat(20)}`).success).toBe(false);
  });
});

describe('loginSchema', () => {
  it('accepts valid credentials', () => {
    const result = loginSchema.safeParse({ email: 'user@example.com', password: 'secret123' });
    expect(result.success).toBe(true);
  });

  it('rejects invalid email', () => {
    expect(loginSchema.safeParse({ email: 'notanemail', password: 'pass' }).success).toBe(false);
    expect(loginSchema.safeParse({ email: '', password: 'pass' }).success).toBe(false);
  });

  it('rejects empty password', () => {
    expect(loginSchema.safeParse({ email: 'a@b.com', password: '' }).success).toBe(false);
  });
});

describe('telegramCredentialsSchema', () => {
  const valid = { api_id: '12345678', api_hash: 'abcdef1234567890abcdef1234567890', phone_number: '+79991234567' };

  it('accepts valid credentials', () => {
    expect(telegramCredentialsSchema.safeParse(valid).success).toBe(true);
  });

  it('transforms api_id string to number', () => {
    const result = telegramCredentialsSchema.safeParse(valid);
    if (result.success) {
      expect(typeof result.data.api_id).toBe('number');
      expect(result.data.api_id).toBe(12345678);
    }
  });

  it('rejects non-numeric api_id', () => {
    expect(telegramCredentialsSchema.safeParse({ ...valid, api_id: 'abc' }).success).toBe(false);
  });

  it('rejects non-hex api_hash', () => {
    expect(telegramCredentialsSchema.safeParse({ ...valid, api_hash: 'not-hex-!!!!' }).success).toBe(false);
  });

  it('rejects invalid phone', () => {
    expect(telegramCredentialsSchema.safeParse({ ...valid, phone_number: '89991234567' }).success).toBe(false);
  });
});

describe('agentSettingsSchema', () => {
  it('accepts valid settings', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'My Agent',
      soul_prompt: 'Some personality',
      system_prompt: 'You are an AI assistant',
    });
    expect(result.success).toBe(true);
  });

  it('rejects empty name', () => {
    expect(agentSettingsSchema.safeParse({ name: '', soul_prompt: '', system_prompt: '' }).success).toBe(false);
  });

  it('rejects too long soul_prompt', () => {
    expect(agentSettingsSchema.safeParse({
      name: 'Agent',
      soul_prompt: 'x'.repeat(50_001),
      system_prompt: '',
    }).success).toBe(false);
  });

  it('trims whitespace from name', () => {
    const result = agentSettingsSchema.safeParse({
      name: '  My Agent  ',
      soul_prompt: '',
      system_prompt: '',
    });
    if (result.success) {
      expect(result.data.name).toBe('My Agent');
    }
  });
});
