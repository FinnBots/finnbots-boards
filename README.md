# FinnBots boards

The leaderboard data every FinnBots game reads (`boards/`), published from the Solana chain every 15 minutes by
`.github/workflows/scan.yml`, so a paid run reaches its board whether or not anyone's computer is awake.

It runs the FinnBots scanner's treasury scan, unchanged, and keeps only what the boards need (`state/`): every value in
this repo is public chain data. It holds no credential for any game, and pays nothing.
