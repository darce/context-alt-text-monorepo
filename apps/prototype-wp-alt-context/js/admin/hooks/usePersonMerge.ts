import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { previewPersonMerge, commitPersonMerge, undoPersonMerge } from '../api/personMergeApi';
import { queryKeys } from '../api/queryKeys';

export const usePersonMerge = () => {
  const client = useQueryClient();
  const [undoToken, setUndoToken] = useState<string | null>(null);
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: queryKeys.roster.all });
    void client.invalidateQueries({ queryKey: queryKeys.clusters.all });
  };
  const preview = useMutation({ mutationFn: previewPersonMerge });
  const commit = useMutation({ mutationFn: commitPersonMerge, onSuccess: (result) => {
    setUndoToken(result.undo_token);
    invalidate();
  } });
  const undo = useMutation({ mutationFn: undoPersonMerge, onSuccess: invalidate });
  return { preview, commit, undo, undoToken };
};
