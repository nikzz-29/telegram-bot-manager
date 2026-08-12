# English locale: the in-DM manual — how the bot is built, how the AI works, what
# each command does. Keys must match ru/guide.ftl exactly.
#
# Why a separate file: this is the longest and least frequently edited copy in the
# project. dm.ftl holds button labels and short answers that change alongside the
# handlers; this holds the text people read end to end.
#
# The constraint that is easy to forget: Telegram caps a message at 4096
# characters and nothing here checks it for us — the sender drops an over-long
# message silently. Hence pages rather than one wall of text.
