import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/copy';
import {
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  GUIDED_NAME_CHOICE,
  createGuidedDemoState,
  createGuidedScenario,
  type GuidedDemoState,
} from '../../../guidedPrototype/state';
import { GuidedDescriptionReview, type GuidedDescriptionReviewActions } from '../GuidedDescriptionReview';

vi.mock('../GuidedLiveDescriptionPanel', () => ({
  GuidedLiveDescriptionPanel: (): never => {
    throw new Error('unreachable guided live status');
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const readyState = (
  draftText: string,
  draftOrigin: GuidedDemoState['draftOrigin'] = GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE,
): GuidedDemoState => ({
  ...createGuidedDemoState(),
  choices: {
    left: GUIDED_NAME_CHOICE.INCLUDE,
    right: GUIDED_NAME_CHOICE.INCLUDE,
  },
  draftText,
  draftOrigin,
  draftStatus: GUIDED_DRAFT_STATUS.READY,
  draftVersion: 1,
  previewedVersion: 1,
});

const reviewActions = (): GuidedDescriptionReviewActions => ({
  onEdit: vi.fn(),
  onDraftInput: vi.fn(),
  onPreview: vi.fn(),
  onKeep: vi.fn(),
  onRetryFixture: vi.fn(),
  onRestore: vi.fn(),
  onApply: vi.fn(),
  onUndo: vi.fn(),
});

describe('GuidedDescriptionReview editor', () => {
  it('starts taller, grows with long edits, and remeasures after a width or text-size change', () => {
    let contentHeight = 180;
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    const { rerender } = render(
      <GuidedDescriptionReview scenario={scenario} state={readyState('A short saved draft.')} actions={actions} />,
    );
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      get: () => contentHeight,
    });

    expect(editor).toHaveAttribute('rows', '8');

    const longGpuDraft = 'A long GPU draft with enough detail to wrap at narrow widths. '.repeat(12);
    editor.style.border = '0px';
    fireEvent.change(editor, { target: { value: longGpuDraft } });
    expect(editor).toHaveStyle({ height: '180px' });

    contentHeight = 420;
    fireEvent(window, new Event('resize'));
    expect(editor).toHaveStyle({ height: '420px' });

    rerender(<GuidedDescriptionReview scenario={scenario} state={readyState(longGpuDraft)} actions={actions} />);
    contentHeight = 640;
    fireEvent(window, new Event('resize'));
    expect(editor).toHaveStyle({ height: '640px' });
    expect(actions.onPreview).not.toHaveBeenCalled();
  });

  it('includes border widths when applying a border-box height', () => {
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    render(<GuidedDescriptionReview scenario={scenario} state={readyState('A saved draft.')} actions={actions} />);
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      get: () => 220,
    });
    Object.assign(editor.style, {
      boxSizing: 'border-box',
      paddingTop: '12px',
      paddingBottom: '12px',
      borderTop: '2px solid black',
      borderBottom: '3px solid black',
    });

    fireEvent.input(editor);

    expect(editor).toHaveStyle({ height: '225px' });
  });

  it('keeps a manually enlarged editor height while content is remeasured', () => {
    let contentHeight = 180;
    let editorHeight = 180;
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    render(<GuidedDescriptionReview scenario={scenario} state={readyState('A saved draft.')} actions={actions} />);
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      get: () => contentHeight,
    });
    editor.style.border = '0px';
    vi.spyOn(editor, 'getBoundingClientRect').mockImplementation(() => ({ height: editorHeight }) as DOMRect);
    fireEvent.mouseDown(editor);
    editorHeight = 420;
    fireEvent.mouseUp(editor);

    contentHeight = 200;
    fireEvent(window, new Event('resize'));
    expect(editor).toHaveStyle({ height: `${editorHeight}px` });
  });

  it('remeasures after a native resize release outside the textarea', () => {
    let contentHeight = 180;
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    render(<GuidedDescriptionReview scenario={scenario} state={readyState('A saved draft.')} actions={actions} />);
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      get: () => contentHeight,
    });
    editor.style.border = '0px';

    fireEvent.pointerDown(editor);
    contentHeight = 320;
    fireEvent.pointerUp(window);
    fireEvent(window, new Event('resize'));

    expect(editor).toHaveStyle({ height: '320px' });
  });

  it('does not pin autoheight after an ordinary click', () => {
    let contentHeight = 180;
    let editorHeight = 180;
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    render(<GuidedDescriptionReview scenario={scenario} state={readyState('A saved draft.')} actions={actions} />);
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      get: () => contentHeight,
    });
    editor.style.border = '0px';
    vi.spyOn(editor, 'getBoundingClientRect').mockImplementation(() => ({ height: editorHeight }) as DOMRect);

    fireEvent.pointerDown(editor);
    fireEvent.pointerUp(editor);
    contentHeight = 120;
    editorHeight = 120;
    fireEvent(window, new Event('resize'));

    expect(editor).toHaveStyle({ height: '120px' });
  });

  it('uses a supplied label only for recorded samples, keeping edited origin distinct', () => {
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    const recordedLabel = 'Saved from the public recorded walkthrough.';
    const { rerender } = render(
      <GuidedDescriptionReview
        scenario={scenario}
        state={readyState('Recorded sample.')}
        actions={actions}
        recordedOriginLabel={recordedLabel}
      />,
    );

    expect(screen.getByText(recordedLabel)).toBeInTheDocument();

    rerender(
      <GuidedDescriptionReview
        scenario={scenario}
        state={readyState('Visitor edit.', GUIDED_DRAFT_ORIGIN.VISITOR_EDIT)}
        actions={actions}
        recordedOriginLabel={recordedLabel}
      />,
    );

    expect(screen.getByText(guidedCopy('draft.origin_edited'))).toBeInTheDocument();
    expect(screen.queryByText(recordedLabel)).not.toBeInTheDocument();
  });
});

describe('a failing live panel does not take the lesson with it', () => {
  it('keeps the draft, apply controls and demo copy on screen', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { GuidedPrototypePage } = await import('../GuidedPrototypePage');
    const user = userEvent.setup();

    render(<GuidedPrototypePage />);

    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
    expect(screen.getByRole('heading', { name: guidedCopy('step.apply') })).toBeInTheDocument();
    expect(screen.getByTestId('demo-apply')).toBeInTheDocument();
    expect(screen.getByTestId('demo-applied-image')).toBeInTheDocument();

    fireEvent.click(
      within(screen.getByTestId('name-choice-left')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Justin Trudeau' }),
      }),
    );
    fireEvent.click(
      within(screen.getByTestId('name-choice-right')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Katy Perry' }),
      }),
    );

    const edited = 'Draft still works after the live panel crashed.';
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(screen.getByTestId('demo-apply'));

    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', edited);
    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
  });
});
