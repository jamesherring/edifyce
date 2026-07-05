// A small, self-contained formal system that compiles cleanly and can verify a
// simple proof. Used to pre-fill the editors so the app is usable on first load.
export const EXAMPLE_SYSTEM = `FormalSystem Minimal:

    Regex anything:
        ^[a-z ]+$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: anything
        behaviour: none
`;

export const EXAMPLE_PROOF = `hello world`;
