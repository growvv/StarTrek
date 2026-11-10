# create_note

**Intent**: Create a text note titled {note_title} with content {note_content}.
**Inputs**: note_title (required): Title text to store for the new note., note_content (required): Body text to store for the new note.
**Preconditions**: - The Omni Notes app is open on the notes list screen. - The expandable floating action menu is available. - A text-note editor is not already active.
**Postconditions**: - A saved note with title {note_title} and content {note_content} is present. - The app is back on the notes list screen, where the note card for {note_title} and {note_content} is visible.
**Effects/Outputs**: - A new text note record is created and persisted. - The note editor is closed, leaving the list view active.
**Steps**:
1. Click the expandable floating action menu button `it.feio.android.omninotes.foss:id/fab_expand_menu_button`.
2. Click the text-note creation action `it.feio.android.omninotes.foss:id/fab_note` to open a blank note editor.
3. Enter {note_title} into the title field `it.feio.android.omninotes.foss:id/detail_title`.
4. Enter {note_content} into the content field `it.feio.android.omninotes.foss:id/detail_content`.
5. Press the system Back key once to dismiss the on-screen keyboard or clear EditText focus while remaining on the note editor.
6. Press the system Back key a second time to exit the note editor, commit/save the note, and return to the notes list screen.
**Evidence**: traces omninotes-create-note-2; 1/1 successes
