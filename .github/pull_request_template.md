# Pull Request

## Description

<!-- Provide a brief description of the changes in this PR -->

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Refactoring (no functional changes, code improvements)
- [ ] Documentation update
- [ ] Test coverage improvement

## Related Issues

<!-- Link to related issues, e.g., "Fixes #123" or "Relates to #456" -->

## Architecture Compliance Checklist

### Component Standards

- [ ] All components under 300 lines (routes under 400 lines)
- [ ] useState count ≤ 5 per file (consider `useReducer` if more)
- [ ] useEffect count ≤ 3 per file (extract custom hooks if more)
- [ ] No prop drilling beyond 2 levels deep
- [ ] Components have single, focused responsibility

### Radix UI Requirements

- [ ] No native `<select>` elements (use `@radix-ui/react-select`)
- [ ] No native `<dialog>` elements (use `@radix-ui/react-dialog`)
- [ ] No native checkbox inputs (use `@radix-ui/react-checkbox`)
- [ ] No native radio inputs (use `@radix-ui/react-radio-group`)
- [ ] All Radix UI components properly styled

### Code Quality

- [ ] TypeScript used for all new modules in `js/` directory
- [ ] All functions/components have JSDoc comments with `@param`, `@returns`, `@example`
- [ ] Props interfaces documented with descriptions
- [ ] Complex logic extracted into named helper functions
- [ ] No code duplication (DRY principle followed)

### Testing

- [ ] Unit tests added/updated for new components
- [ ] Integration tests cover component interactions
- [ ] All tests passing (`npm run test`)
- [ ] Test coverage maintained at 80%+
- [ ] Visual regression tests added (Storybook stories) if UI changes

### Validation

- [ ] ESLint passes (`npm run lint`)
- [ ] Architecture compliance check passes (`npm run check:architecture`)
- [ ] Prettier formatting applied (`npm run format`)
- [ ] No TypeScript errors (`tsc --noEmit`)

## Breaking Changes

<!-- List any breaking changes and migration steps required -->

## Screenshots / Videos

<!-- If applicable, add screenshots or videos demonstrating the changes -->

## Additional Notes

<!-- Any additional information reviewers should know -->

## Checklist Before Merge

- [ ] PR has been reviewed and approved
- [ ] All CI checks passing
- [ ] Branch is up to date with main/master
- [ ] Documentation updated if needed
- [ ] Changelog updated (if applicable)
