# Record with: vhs docs/demo.tape   (run from the repository root; replays recorded data, no key)
Output docs/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1060
Set Height 640
Set Padding 14
Set TypingSpeed 18ms
Set Framerate 10
Set PlaybackSpeed 1

Hide
Type "export PS1='$ ' PS2='  ' && unset JEV_API_KEY TYPESAFE_API_KEY"
Enter
Type "clear"
Enter
Show

Type "python3 jev_cascade.py --demo run examples/tickets.jsonl examples/questions.json examples/policy.json \"
Enter
Type "--out /tmp/demo_out.jsonl"
Sleep 400ms
Enter
Sleep 2500ms

Hide
Type "clear"
Enter
Show

Type "python3 jev_cascade.py report /tmp/demo_out.jsonl"
Sleep 400ms
Enter
Sleep 9s
