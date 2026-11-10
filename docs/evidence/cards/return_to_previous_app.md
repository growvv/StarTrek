# return_to_previous_app

**Intent**: Leave {current_app} and return to {previous_app} with a single system Back action, without interacting with in-app content.
**Inputs**: current_app (required): Name of the app currently in the foreground to leave., previous_app (required): Name of the prior app in the back stack to return to.
**Preconditions**: - {current_app} is in the foreground. - {previous_app} is the immediately previous app in the navigation/back stack. - The system Back control (ImageView id='com.google.android.apps.nexuslauncher:id/back', desc='返回') is available.
**Postconditions**: - {current_app} is no longer the foreground app. - {previous_app} is in the foreground. - The system Back control has been activated once.
**Effects/Outputs**: - The foreground app changes from {current_app} to {previous_app}. - No in-app data is created, edited, deleted, or selected.
**Steps**:
1. Press the system Back control (ImageView id='com.google.android.apps.nexuslauncher:id/back', desc='返回') once to leave {current_app} and return to {previous_app}.
**Evidence**: traces omninotes-delete-1; 1/1 successes
