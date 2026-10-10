import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { guidedCopy } from '../../admin/guidedPrototype/copy';
import { guidedCopy as publicCopy } from '../../admin/guidedPrototype/publicGuideCopy';
import { RecordedWalkthrough } from '../../admin/guidedPrototype/RecordedWalkthrough';
import { createGuidedScenario, type GuidedImageKey } from '../../admin/guidedPrototype/state';

const discardedCaption = 'Discarded manual caption naming Katy Perry.';
const replacement = createGuidedScenario().samples.tribeca['justin-trudeau'];

const nameRadio = (imageKey: GuidedImageKey, position: 'left' | 'right', option: 'include' | 'omit') =>
  within(screen.getByTestId(`name-choice-${imageKey}-${position}`)).getByRole('radio', {
    name:
      option === 'include'
        ? publicCopy('names.use.public', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
        : publicCopy('names.omit.public'),
  });

const choose = (imageKey: GuidedImageKey, position: 'left' | 'right', option: 'include' | 'omit'): void => {
  fireEvent.click(nameRadio(imageKey, position, option));
};

const answerNames = (imageKey: GuidedImageKey): void => {
  choose(imageKey, 'left', 'include');
  choose(imageKey, 'right', 'include');
};

const editor = (imageKey: GuidedImageKey) =>
  within(screen.getByTestId(`guided-draft-field-${imageKey}`)).getByRole('textbox', {
    name: publicCopy('draft.field_label.public'),
  });

const adminEditor = (imageKey: GuidedImageKey): HTMLTextAreaElement =>
  within(screen.getByTestId(`guided-description-review-${imageKey}`)).getByRole<HTMLTextAreaElement>('textbox', {
    name: guidedCopy('draft.label'),
  });

const preview = async (user: ReturnType<typeof userEvent.setup>): Promise<void> => {
  await user.click(
    within(screen.getByTestId('guided-description-review-tribeca')).getByRole('button', {
      name: guidedCopy('draft.next'),
    }),
  );
};

const confirmAdminReplacement = async (user: ReturnType<typeof userEvent.setup>): Promise<void> => {
  await user.click(
    within(screen.getByRole('dialog', { name: guidedCopy('names.change_title') })).getByRole('button', {
      name: guidedCopy('names.change_confirm'),
    }),
  );
};

const edit = (imageKey: GuidedImageKey, text: string): void => {
  fireEvent.change(editor(imageKey), { target: { value: text } });
};

const replacementDialog = () => screen.getByRole('dialog', { name: publicCopy('name_change.title.public') });

const confirmReplacement = async (user: ReturnType<typeof userEvent.setup>): Promise<void> => {
  await user.click(within(replacementDialog()).getByRole('button', { name: publicCopy('name_change.confirm.public') }));
};

const openHistory = async (user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> => {
  const review = screen.getByTestId('guided-description-review-tribeca');
  await user.click(within(review).getByText(guidedCopy('draft.history'), { selector: 'summary' }));
  return review;
};

describe('public walkthrough pending draft ownership', () => {
  it('keeps a confirmed replacement after another photo action and archives the discarded edit', async () => {
    const user = userEvent.setup({ delay: null });
    render(<RecordedWalkthrough scope="public" />);
    answerNames('tribeca');
    await user.clear(editor('tribeca'));
    await user.type(editor('tribeca'), discardedCaption);
    choose('tribeca', 'right', 'omit');

    const dialog = replacementDialog();
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleDescription(publicCopy('name_change.body.public'));
    expect(within(dialog).getByRole('button', { name: publicCopy('name_change.keep.public') })).toHaveFocus();
    await confirmReplacement(user);

    expect(nameRadio('tribeca', 'right', 'omit')).toBeChecked();
    expect(nameRadio('tribeca', 'right', 'omit')).toHaveFocus();
    expect(editor('tribeca')).toHaveValue(replacement);
    choose('coachella', 'left', 'include');
    // TEST-06: the unfixed cross-photo flush replaces this with discardedCaption.
    expect(editor('tribeca')).toHaveValue(replacement);

    const review = await openHistory(user);
    expect(within(review).getByText(discardedCaption)).toBeVisible();
    expect(within(review).getByRole('button', { name: guidedCopy('draft.copy_revision') })).toBeEnabled();
  }, 30_000);

  it.each(['full', 'copy_only'] as const)('keeps an explicit %s restore after another photo action', async (mode) => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);
    answerNames('tribeca');
    edit('tribeca', discardedCaption);
    choose('tribeca', 'right', 'omit');
    await confirmReplacement(user);
    if (mode === 'full') {
      edit('tribeca', 'Intervening edit before aligning the archived name choices.');
      choose('tribeca', 'right', 'include');
      await confirmReplacement(user);
    }
    const supersededCaption = `Unsaved caption superseded by ${mode} restore.`;
    edit('tribeca', supersededCaption);
    const review = await openHistory(user);
    const revision = within(review).getByText(discardedCaption).closest('li');
    if (revision === null) {
      throw new Error('Missing archived manual caption.');
    }
    await user.click(
      within(revision).getByRole('button', {
        name: guidedCopy(mode === 'full' ? 'draft.restore_revision' : 'draft.copy_revision'),
      }),
    );
    expect(editor('tribeca')).toHaveValue(discardedCaption);
    choose('coachella', 'left', 'include');
    expect(editor('tribeca')).toHaveValue(discardedCaption);
    expect(within(review).getByText(supersededCaption)).toBeVisible();
    expect(nameRadio('tribeca', 'right', mode === 'full' ? 'include' : 'omit')).toBeChecked();
  });

  it('preserves the other photo unsaved edit through replacement and applies its visible text', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);
    answerNames('tribeca');
    answerNames('coachella');
    const otherCaption = 'Unrelated Coachella edit still awaiting acceptance.';
    edit('coachella', otherCaption);
    edit('tribeca', discardedCaption);
    choose('tribeca', 'right', 'omit');
    await confirmReplacement(user);
    expect(editor('coachella')).toHaveValue(otherCaption);

    await user.click(screen.getByTestId('demo-apply-coachella'));
    expect(screen.getByTestId('guided-photo-coachella').querySelector('img.acx-guided-page__image')).toHaveAttribute(
      'alt',
      otherCaption,
    );
    expect(editor('tribeca')).toHaveValue(replacement);
    await user.click(screen.getByTestId('demo-undo-coachella'));
    expect(editor('tribeca')).toHaveValue(replacement);
    expect(editor('coachella')).toHaveValue(otherCaption);
  });

  it.each(['Keep edits', 'Escape'])('preserves edits and choices when cancelling with %s', async (method) => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);
    answerNames('tribeca');
    edit('tribeca', discardedCaption);
    choose('tribeca', 'right', 'omit');
    if (method === 'Escape') {
      await user.keyboard('{Escape}');
    } else {
      await user.click(
        within(replacementDialog()).getByRole('button', { name: publicCopy('name_change.keep.public') }),
      );
    }
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(nameRadio('tribeca', 'right', 'omit')).toHaveFocus();
    expect(nameRadio('tribeca', 'right', 'include')).toBeChecked();
    choose('coachella', 'left', 'include');
    expect(editor('tribeca')).toHaveValue(discardedCaption);
  });

  it('clears pending edits and archived recovery when starting over', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);
    answerNames('tribeca');
    edit('tribeca', discardedCaption);
    choose('tribeca', 'right', 'omit');
    await confirmReplacement(user);
    edit('tribeca', 'Another uncommitted caption before reset.');
    await user.click(screen.getByRole('button', { name: publicCopy('reset.confirm.public') }));
    await user.click(
      within(screen.getByRole('dialog', { name: publicCopy('reset.title.public') })).getByRole('button', {
        name: publicCopy('reset.confirm.public'),
      }),
    );
    expect(nameRadio('tribeca', 'left', 'include')).toHaveFocus();
    expect(screen.queryByText(guidedCopy('draft.history'), { selector: 'summary' })).not.toBeInTheDocument();
    answerNames('tribeca');
    choose('coachella', 'left', 'include');
    expect(editor('tribeca')).toHaveValue(createGuidedScenario().samples.tribeca.both);
  });
});

describe('mounted editor acceptance controls', () => {
  it.each(['replacement', 'full', 'copy_only'] as const)(
    'keeps an admin %s after accepting manual input with Preview',
    async (action) => {
      const user = userEvent.setup({ delay: null });
      render(<RecordedWalkthrough scope="admin" />);
      answerNames('tribeca');
      await user.clear(adminEditor('tribeca'));
      await user.type(adminEditor('tribeca'), discardedCaption);
      expect(screen.getByTestId('demo-apply-tribeca')).toBeDisabled();
      await preview(user);
      expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();

      choose('tribeca', 'right', 'omit');
      await confirmAdminReplacement(user);
      expect(adminEditor('tribeca')).toHaveValue(replacement);
      choose('coachella', 'left', 'include');
      expect(adminEditor('tribeca')).toHaveValue(replacement);
      const review = await openHistory(user);
      expect(within(review).getByText(discardedCaption)).toBeVisible();

      if (action !== 'replacement') {
        if (action === 'full') {
          choose('tribeca', 'right', 'include');
        }
        const superseded = `Previewed caption before ${action} restore.`;
        await user.clear(adminEditor('tribeca'));
        await user.type(adminEditor('tribeca'), superseded);
        await preview(user);
        expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();
        const revision = within(review).getByText(discardedCaption).closest('li');
        if (revision === null) {
          throw new Error('Missing archived manual caption.');
        }
        await user.click(
          within(revision).getByRole('button', {
            name: guidedCopy(action === 'full' ? 'draft.restore_revision' : 'draft.copy_revision'),
          }),
        );
        expect(adminEditor('tribeca')).toHaveValue(discardedCaption);
        expect(screen.getByTestId('demo-apply-tribeca')).toBeDisabled();
        choose('coachella', 'right', 'include');
        expect(adminEditor('tribeca')).toHaveValue(discardedCaption);
        expect(within(review).getByText(superseded)).toBeVisible();
        expect(nameRadio('tribeca', 'right', action === 'full' ? 'include' : 'omit')).toBeChecked();
      }
    },
    30_000,
  );

  it.each(['public', 'admin'] as const)(
    'preserves selection and mid-sentence typing through %s renders and acceptance',
    async (scope) => {
      const user = userEvent.setup({ delay: null });
      const { rerender } = render(<RecordedWalkthrough scope={scope} />);
      answerNames('tribeca');
      const field = (scope === 'admin' ? adminEditor('tribeca') : editor('tribeca')) as HTMLTextAreaElement;
      await user.clear(field);
      await user.type(field, 'Justin and Katy at the event.');
      await user.keyboard('{Home}{ArrowRight>7}{Shift>}{ArrowRight>4}{/Shift}');
      expect(field.selectionStart).toBe(7);
      expect(field.selectionEnd).toBe(11);
      rerender(<RecordedWalkthrough scope={scope} />);
      expect(
        screen.getByRole('textbox', {
          name: scope === 'admin' ? guidedCopy('draft.label') : publicCopy('draft.field_label.public'),
        }),
      ).toBe(field);
      expect(field).toHaveFocus();
      expect(field.selectionStart).toBe(7);
      expect(field.selectionEnd).toBe(11);

      await user.keyboard('with ');
      expect(field).toHaveValue('Justin with Katy at the event.');
      expect(field.selectionStart).toBe(12);
      expect(field.selectionEnd).toBe(12);
      await user.keyboard('{ArrowLeft>5}');
      // A parent state update accepts the edit without moving focus away from it.
      choose('coachella', 'left', 'include');
      expect(field).toHaveFocus();
      expect(field).toHaveValue('Justin with Katy at the event.');
      expect(field.selectionStart).toBe(7);
      expect(field.selectionEnd).toBe(7);
      if (scope === 'admin') {
        await preview(user);
        expect(field.selectionStart).toBe(7);
        expect(field.selectionEnd).toBe(7);
        expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();
      }
      await user.click(field);
      await user.keyboard('{Home}{ArrowRight>7}still ');
      expect(field).toHaveValue('Justin still with Katy at the event.');
      expect(field.selectionStart).toBe(13);
      expect(field.selectionEnd).toBe(13);
    },
    30_000,
  );

  it.each(['replacement', 'restore'] as const)(
    'consumes repeated identical input without invalidating Preview or overwriting a later %s',
    async (action) => {
      const user = userEvent.setup({ delay: null });
      render(<RecordedWalkthrough scope="admin" />);
      answerNames('tribeca');
      await user.clear(adminEditor('tribeca'));
      await user.type(adminEditor('tribeca'), discardedCaption);
      choose('tribeca', 'right', 'omit');
      await confirmAdminReplacement(user);

      const repeatedCaption = 'Same accepted caption entered twice.';
      await user.clear(adminEditor('tribeca'));
      await user.type(adminEditor('tribeca'), repeatedCaption);
      await preview(user);
      expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();
      await user.clear(adminEditor('tribeca'));
      await user.type(adminEditor('tribeca'), repeatedCaption);
      await preview(user);
      choose('coachella', 'left', 'include');
      expect(adminEditor('tribeca')).toHaveValue(repeatedCaption);
      expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();

      let expectedCaption: string;
      if (action === 'replacement') {
        choose('tribeca', 'right', 'include');
        await confirmAdminReplacement(user);
        expectedCaption = createGuidedScenario().samples.tribeca.both;
      } else {
        const review = await openHistory(user);
        const revision = within(review).getByText(discardedCaption).closest('li');
        if (revision === null) {
          throw new Error('Missing archived manual caption.');
        }
        await user.click(within(revision).getByRole('button', { name: guidedCopy('draft.copy_revision') }));
        expectedCaption = discardedCaption;
      }
      expect(adminEditor('tribeca')).toHaveValue(expectedCaption);
      choose('coachella', 'right', 'include');
      expect(adminEditor('tribeca')).toHaveValue(expectedCaption);
      const review = screen.getByTestId('guided-description-review-tribeca');
      expect(within(review).getByText(repeatedCaption, { selector: 'li p' })).toBeInTheDocument();
    },
    30_000,
  );
});
