import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { availableParallelism } from 'node:os';
import path from 'path';

const domTests = [
  'js/**/*.{test,spec}.tsx',
  // Keep browser-backed imports in jsdom even when a test currently mocks that path.
  'js/admin/api/__tests__/recognitionApi.test.ts',
  'js/admin/api/recognition/__tests__/identityActionsApiAcceptMerge.test.ts',
  'js/admin/api/__tests__/workbenchMediaApi.test.ts',
  'js/admin/utils/__tests__/adminUrls.test.ts',
  'js/admin/utils/__tests__/http.test.ts',
  'js/components/ui/__tests__/cropFaceFromImage.test.ts',
  'js/admin/api/__tests__/describeApi.test.ts',
  'js/admin/api/recognition/__tests__/retentionApiExportEnvelope.test.ts',
  'js/admin/utils/__tests__/retryPolicy.test.ts',
  'js/admin/api/__tests__/config.test.ts',
  'js/admin/api/__tests__/personMergeApi.test.ts',
  'js/admin/api/__tests__/settingsResponseContract.test.ts',
  'js/admin/api/describeApi.test.ts',
  'js/admin/api/recognition/__tests__/clusterApiMutationsRevertSignal.test.ts',
  'js/admin/api/recognition/__tests__/clusterApiMutationsSplitSignal.test.ts',
  'js/admin/api/recognition/__tests__/clusterApiQueries.repairPending.test.ts',
  'js/admin/api/recognition/__tests__/envelopeMetadata.test.ts',
  'js/admin/api/recognition/__tests__/scanApiBatching.test.ts',
  'js/admin/api/recognition/__tests__/scanApiSignal.test.ts',
  'js/admin/api/recognition/__tests__/syncApi.reclaimer.test.ts',
  'js/admin/guidedPrototype/describeRunParse.test.ts',
  'js/admin/hooks/__tests__/jobStateMachineUtils.test.ts',
  'js/admin/hooks/__tests__/recognitionJobHistoryUtils.test.ts',
  'js/admin/utils/__tests__/appError.test.ts',
  'js/admin/utils/__tests__/logger.test.ts',
  'js/admin/utils/__tests__/warmingDeadline.test.ts',
  'js/admin/__tests__/routeHelpers.test.ts',
  'js/guide/__tests__/publicGuideWatch.test.ts',
  'js/public/__tests__/demo-describe.test.ts',
  'js/admin/api/__tests__/guidedLiveMediaId.test.ts',
  'js/admin/api/__tests__/refreshRestNonce.test.ts',
  'js/admin/api/__tests__/registerConfig.test.ts',
  'js/admin/api/__tests__/rosterApiCancellation.test.ts',
  'js/admin/hooks/__tests__/activeDescribeRun.test.ts',
  'js/admin/hooks/__tests__/describeOperationStore.test.ts',
  'js/admin/hooks/__tests__/useActivityStatus.test.ts',
  'js/admin/hooks/__tests__/useGpuServiceStatus.test.ts',
  'js/admin/hooks/__tests__/useJobCoordination.test.ts',
  'js/admin/hooks/__tests__/useJobPersistence.test.ts',
  'js/admin/hooks/__tests__/useJobStateMachine.test.ts',
  'js/admin/hooks/__tests__/useJobStateMachineDerivedState.test.ts',
  'js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts',
  'js/admin/hooks/__tests__/useJobStateMachineMutations.test.ts',
  'js/admin/hooks/__tests__/useMediaSelectionState.test.ts',
  'js/admin/hooks/__tests__/useScrollRestoration.test.ts',
  'js/admin/hooks/__tests__/useSyncOffline.test.ts',
  'js/admin/utils/__tests__/httpModuleGraph.test.ts',
  'js/admin/utils/__tests__/moduleLoadOrder.test.ts',
  'js/components/ui/__tests__/useDurableFaceThumb.test.ts',
  'js/admin/pages/guided/__tests__/GuidedUxMap.contract.test.ts',
  'js/admin/pages/retention/__tests__/useRetentionPageState.test.ts',
  'js/admin/pages/roster/hooks/__tests__/useClusterDragDrop.test.ts',
  'js/admin/pages/roster/hooks/__tests__/useClusterMediaMap.test.ts',
];

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // WordPress installs the plugin below a variable URL, not the site root.
  base: './',
  publicDir: false,
  build: {
    sourcemap: mode === 'development' ? 'inline' : false,
    minify: mode === 'production' ? 'esbuild' : false,
    manifest: true,
    outDir: path.resolve(__dirname, 'public/assets/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        admin: path.resolve(__dirname, 'js/admin/main.tsx'),
        'attachment-edit': path.resolve(__dirname, 'js/attachment-edit/main.tsx'),
        guide: path.resolve(__dirname, 'js/guide/main.tsx'),
        'guide-watch': path.resolve(__dirname, 'js/guide/publicGuideWatch.ts'),
        'public-demo-tokens': path.resolve(__dirname, 'js/public/demo-tokens.scss'),
      },
    },
  },
  test: {
    globals: true,
    pool: 'forks',
    // Keep forks below laptop memory pressure while retaining parallelism on constrained hosts.
    maxWorkers: Math.max(2, Math.floor(availableParallelism() / 2)),
    projects: [
      {
        extends: true,
        test: {
          name: 'dom',
          environment: 'jsdom',
          setupFiles: ['./vitest.setup.ts', './vitest.setup.dom.ts'],
          include: domTests,
        },
      },
      {
        extends: true,
        test: {
          name: 'node',
          environment: 'node',
          setupFiles: ['./vitest.setup.ts'],
          // Playwright itself only collects *.spec.ts; these are harness unit tests.
          include: ['js/**/*.{test,spec}.ts', 'tests/e2e/**/*.test.ts'],
          exclude: [...configDefaults.exclude, ...domTests],
        },
      },
    ],
  },
}));
