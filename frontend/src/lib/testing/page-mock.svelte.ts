// A reactive stand-in for `$app/state`'s `page`, for tests that need to drive a
// route-param change. Runes can't live in a `.test.ts`, so the reactive state
// lives here; a test mocks `$app/state` with this module and mutates
// `page.params.id` to simulate navigation. Only the fields our pages read are
// present (currently just `params`).
export const page = $state<{ params: Record<string, string> }>({ params: {} });
