# AI Code Review Framework Card

## Before you generate

1. Have I used the application and seen the behaviour myself?
2. Can I state, in one sentence, what I want changed?
3. Am I asking a question before issuing an instruction?

## When reviewing the response

4. Did it change only what I asked for?
5. Can I explain every line it produced?
6. Did it delete the old code, or only stop using it?
7. Did it add a library, default, or fallback I did not ask for?
8. Does the change protect the action, or only the page?

## Before you accept

9. Have I re-run the exact failure that prompted the change?
10. Have I checked that a normal case still works?
11. Have I logged the prompt, change, and verification?
