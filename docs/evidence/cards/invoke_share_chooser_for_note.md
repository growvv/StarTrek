# invoke_share_chooser_for_note

**Intent**: Invoke the Android share chooser to share the note titled {note_title} with content {note_content} through another app such as {share_target_label}.
**Inputs**: note_title (required): Title of the note open on the detail screen., note_content (required): Text content of the note to offer to the share chooser., share_target_label (optional): Visible label of an external app target to be offered by the Android share chooser.
**Preconditions**: The note detail screen is open; `it.feio.android.omninotes.foss:id/detail_title` contains {note_title} and `it.feio.android.omninotes.foss:id/detail_content` contains {note_content}; the share control `it.feio.android.omninotes.foss:id/menu_share` (visible label `共享`) is clickable.
**Postconditions**: The Android share chooser is open for {note_title}; `com.android.intentresolver:id/headline` (visible label `分享文本`) is displayed, `android:id/content_preview_text` shows {note_content}, `com.android.intentresolver:id/copy` (visible label `复制文字`) is available, and `com.android.intentresolver:id/item` target controls with visible labels such as {share_target_label} are ready for selection; no final app selection has been made.
**Effects/Outputs**: A text share for {note_content} is emitted and the chooser screen is shown with `com.android.intentresolver:id/headline` (`分享文本`), `android:id/content_preview_text` (`{note_content}`), `com.android.intentresolver:id/copy` (`复制文字`), and `com.android.intentresolver:id/item` controls such as {share_target_label}; no note fields are edited and no external app receives the note until a target is selected.
**Steps**:
1. Click `it.feio.android.omninotes.foss:id/menu_share` (visible label `共享`) on the note detail screen for {note_title} containing {note_content}, so that the Android share chooser opens with {share_target_label} available as a target.
**Evidence**: traces omninotes-share-1; 1/1 successes
