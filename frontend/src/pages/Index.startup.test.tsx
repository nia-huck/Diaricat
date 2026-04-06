import { beforeEach, describe, expect, it } from 'vitest';

import { STARTUP_HANDOFF_STORAGE_KEY, shouldShowStartupHandoff } from '@/pages/Index';

describe('startup handoff session behavior', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('shows handoff on first startup call', () => {
    expect(shouldShowStartupHandoff()).toBe(true);
    expect(window.sessionStorage.getItem(STARTUP_HANDOFF_STORAGE_KEY)).toBe('1');
  });

  it('runs handoff only once per session', () => {
    expect(shouldShowStartupHandoff()).toBe(true);
    expect(shouldShowStartupHandoff()).toBe(false);
  });
});
