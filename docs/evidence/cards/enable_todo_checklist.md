# enable_todo_checklist

**Intent**: Turn the {note_title} note into a to-do checklist with {note_content} as its first checklist item.
**Inputs**: note_title (required): title of the target note to open and convert., note_content (required): existing body text that should be represented as the first unchecked checklist item.
**Preconditions**: The notes list is open and contains a note whose TextView resourceId=`it.feio.android.omninotes.foss:id/note_title` displays {note_title}; {note_content} is present in that note's body; the note is not already in checklist mode.
**Postconditions**: The {note_title} note is saved with checklist mode enabled; {note_content} appears as an unchecked checklist item; the notes-list preview for {note_title} shows a checkbox marker for {note_content}.
**Effects/Outputs**: In the editor, {note_content} is rendered beside a CheckBox and an empty checklist row is added; after returning to the notes list, the TextView with resourceId=`it.feio.android.omninotes.foss:id/note_title` displays {note_title} and the TextView with resourceId=`it.feio.android.omninotes.foss:id/note_content` shows a checkbox marker for {note_content}.
**Steps**:
1. Click the note row whose TextView has resourceId=`it.feio.android.omninotes.foss:id/note_title` and text {note_title}.
2. Click the ImageView with desc=`更多选项`.
3. Click the menu item whose TextView has visible label `启用待办事项列表` and id=`it.feio.android.omninotes.foss:id/title` to convert {note_content} into a checklist row.
4. Press Back to return to the notes list and persist the checklist for {note_title}.
**Evidence**: traces omninotes-checklist-1; 1/1 successes
