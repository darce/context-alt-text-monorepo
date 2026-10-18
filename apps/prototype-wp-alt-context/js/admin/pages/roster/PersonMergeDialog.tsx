import React, { useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { DialogRoot, DialogPortal, DialogOverlay, DialogContent, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import type { RosterEntry } from '../../api/rosterApi';
import { isPersonMergeConflict, personMergeErrorMessage, type PersonMergePreview } from '../../api/personMergeApi';
import type { usePersonMerge } from '../../hooks/usePersonMerge';

interface PersonMergeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loser: RosterEntry;
  entries: RosterEntry[];
  merge: ReturnType<typeof usePersonMerge>;
  onMerged: (preview: PersonMergePreview) => void;
}

export const PersonMergeDialog = ({ open, onOpenChange, loser, entries, merge, onMerged }: PersonMergeDialogProps) => {
  const [loserId, setLoserId] = useState(loser.id);
  const [survivorId, setSurvivorId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  // rg-004 / IDCHIP-1-MUI-R-01: capture the row's Merge trigger before Radix moves
  // focus into the dialog, so Cancel/Escape/backdrop/successful merge can restore it.
  const [triggerElement] = useState<HTMLElement | null>(() =>
    document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const preview = merge.preview.data;
  const pending = merge.preview.isPending || merge.commit.isPending;
  const error = merge.commit.error ?? merge.preview.error;
  const reset = () => { merge.preview.reset(); merge.commit.reset(); };
  const close = (next: boolean) => { if (!pending) onOpenChange(next); };
  return <DialogRoot open={open} onOpenChange={close}>
    <DialogPortal><DialogOverlay /><DialogContent className="acx-person-merge" onCloseAutoFocus={event => {
      event.preventDefault();
      triggerElement?.focus();
    }}>
      <DialogTitle>Merge people</DialogTitle>
      <DialogDescription>Choose the person to keep, then review the merge.</DialogDescription>
      {!preview ? <fieldset disabled={pending}>
        <p>Person to remove: {entries.find(entry => entry.id === loserId)?.name}</p>
        <label htmlFor="merge-search">Search people by name</label>
        <input id="merge-search" type="search" value={search} onChange={event => setSearch(event.target.value)} />
        <label htmlFor="merge-survivor">Person to keep</label>
        <select id="merge-survivor" value={survivorId ?? ''} onChange={event => { setSurvivorId(event.target.value ? Number(event.target.value) : null); reset(); }}>
          <option value="">Choose a person</option>
          {entries.filter(entry => entry.id !== loserId && (entry.id === survivorId || entry.name.toLowerCase().includes(search.toLowerCase()))).map(entry => <option key={entry.id} value={entry.id}>{entry.name || 'Unnamed person'}</option>)}
        </select>
        {entries.filter(entry => entry.id !== loserId).length === 0 && <p>Add another person before merging.</p>}
        <button type="button" disabled={survivorId === null} onClick={() => {
          if (survivorId === null) return;
          setLoserId(survivorId); setSurvivorId(loserId); setSearch(''); reset();
        }}>Swap people</button>
      </fieldset> : <div>
        <p>{preview.survivor.name}: {preview.survivor.cluster_count} face groups (kept)</p>
        <p>{preview.loser.name}: {preview.loser.cluster_count} face groups (removed)</p>
        <p>{preview.loser.name} will be removed; its {preview.loser.cluster_count} face groups move to {preview.survivor.name}. You can undo.</p>
        <p>Tags: {preview.tags.length ? preview.tags.join(', ') : 'No tags'}</p>
        {preview.conflicts.length > 0 && <p role="alert"><AlertCircle aria-hidden="true" />Conflicts prevent this merge. Refresh the preview before trying again.</p>}
      </div>}
      {pending && <p role="status"><Loader2 aria-hidden="true" />{merge.commit.isPending ? 'Merging people…' : 'Loading preview…'}</p>}
      {error && <p role="alert"><AlertCircle aria-hidden="true" />{isPersonMergeConflict(error) ? 'Merge conflict: ' : 'Merge failed: '}{personMergeErrorMessage(error)}</p>}
      <div className="acx-dialog__actions">
        <button type="button" disabled={pending} onClick={() => close(false)}>Cancel</button>
        {preview ? <>
          <button type="button" disabled={pending} onClick={reset}>Change people</button>
          <button type="button" className="acx-button acx-button--primary" disabled={pending || preview.conflicts.length > 0 || isPersonMergeConflict(error)} onClick={() => merge.commit.mutate({ survivor_id: preview.survivor.id, loser_id: preview.loser.id }, { onSuccess: () => { onMerged(preview); onOpenChange(false); } })}>Merge</button>
        </> : <button type="button" className="acx-button acx-button--primary" disabled={pending || survivorId === null} onClick={() => {
          if (survivorId !== null) merge.preview.mutate({ survivor_id: survivorId, loser_id: loserId });
        }}>Preview merge</button>}
      </div>
    </DialogContent></DialogPortal>
  </DialogRoot>;
};
