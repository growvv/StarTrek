# search_notes_by_keyword

**Intent**: Search notes by {keyword} and submit the query so the notes list is filtered to matches for {keyword}.
**Inputs**: keyword (required): Text to search for in the notes list.
**Preconditions**: The notes list screen is displayed and `it.feio.android.omninotes.foss:id/menu_search` (`搜索`) is available.
**Postconditions**: The submitted notes search is active for `{keyword}`; `it.feio.android.omninotes.foss:id/search_src_text` contains `{keyword}`, `it.feio.android.omninotes.foss:id/search_query` shows `搜索: {keyword}`, and the visible notes list is filtered to notes matching `{keyword}`.
**Effects/Outputs**: The notes search UI is opened, `{keyword}` is entered and submitted, and the app displays `it.feio.android.omninotes.foss:id/search_query` with `搜索: {keyword}` plus a filtered notes list. No note is opened or edited.
**Steps**:
1. Click `it.feio.android.omninotes.foss:id/menu_search` (`搜索`) to open the notes search field.
2. Type `{keyword}` into `it.feio.android.omninotes.foss:id/search_src_text` (`在笔记中搜索`).
3. Press the keyboard `Enter` key to submit the search.
**Evidence**: traces omninotes-search-3; 1/1 successes
