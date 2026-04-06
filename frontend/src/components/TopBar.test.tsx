import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockUseAppState } = vi.hoisted(() => ({
  mockUseAppState: vi.fn(),
}));

vi.mock('@/context/AppContext', () => ({
  useAppState: () => mockUseAppState(),
}));

import TopBar from '@/components/TopBar';

type MockDesktopApi = {
  minimize: ReturnType<typeof vi.fn>;
  toggle_maximize: ReturnType<typeof vi.fn>;
  toggle_fullscreen: ReturnType<typeof vi.fn>;
  close_window: ReturnType<typeof vi.fn>;
  start_window_drag: ReturnType<typeof vi.fn>;
  start_window_resize: ReturnType<typeof vi.fn>;
  get_window_state: ReturnType<typeof vi.fn>;
};

const createDesktopApi = (): MockDesktopApi => ({
  minimize: vi.fn().mockResolvedValue(undefined),
  toggle_maximize: vi.fn().mockResolvedValue(undefined),
  toggle_fullscreen: vi.fn().mockResolvedValue(undefined),
  close_window: vi.fn().mockResolvedValue(undefined),
  start_window_drag: vi.fn().mockResolvedValue(true),
  start_window_resize: vi.fn().mockResolvedValue(true),
  get_window_state: vi.fn().mockResolvedValue({ state: 'normal' }),
});

describe('TopBar desktop drag behavior', () => {
  let desktopApi: MockDesktopApi;

  beforeEach(() => {
    desktopApi = createDesktopApi();
    (window as Window & { pywebview?: { api: MockDesktopApi } }).pywebview = { api: desktopApi };
    mockUseAppState.mockReturnValue({
      screen: 'home',
      isBusy: false,
      settings: { fullscreen_on_maximize: false },
      setScreen: vi.fn(),
    });
  });

  it('starts native window drag when mousedown happens in title area', () => {
    render(<TopBar />);
    fireEvent.mouseDown(screen.getByTitle('Arrastrar para mover'), { button: 0 });
    expect(desktopApi.start_window_drag).toHaveBeenCalledTimes(1);
  });

  it('does not start drag when interacting with no-drag controls', () => {
    render(<TopBar />);
    fireEvent.mouseDown(screen.getByTitle('Configuracion'), { button: 0 });
    fireEvent.mouseDown(screen.getByTitle('Ir a Inicio'), { button: 0 });
    fireEvent.mouseDown(screen.getByTitle('Ayuda (proximamente)'), { button: 0 });
    expect(desktopApi.start_window_drag).not.toHaveBeenCalled();
  });

  it('toggles maximize on titlebar double click', () => {
    render(<TopBar />);
    fireEvent.doubleClick(screen.getByTitle('Arrastrar para mover'));
    expect(desktopApi.toggle_maximize).toHaveBeenCalledTimes(1);
  });
});
