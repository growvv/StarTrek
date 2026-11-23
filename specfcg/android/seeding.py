"""Put the data a build's task needs on the device before the agent acts.

A file task needs a file.  Markor 0.3.9 reads `/storage/emulated/0/Documents/
markor` and shows "This directory is empty" until something is there; Amaze
deletes from `Documents`.  An agent cannot create the precondition it is
supposed to start from, and a run that starts from the wrong state measures
the state.

Each entry names the path the build actually reads.  That path is not
guessable — Markor's is stored in the app's own preferences and differs
between versions — so a build with no known path is reported rather than
given a default.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSpec:
    """Where a build keeps the data a task acts on."""

    package: str
    directory: str
    sample_file: str = "sample.txt"
    sample_text: str = "sample text\n"
    # Some crashes need a state an ordinary directory does not have: Amaze
    # 3.3.2's delete runs off the end of an adapter whose list just became
    # empty, which only happens when the directory held one item.  A spec
    # says so rather than leaving the run to hope.
    only_item: bool = False


# Paths read from each build's own storage: Markor stores its notebook
# directory in `shared_prefs/app.xml`, and the 2018 build writes
# `/storage/emulated/0/Documents/markor`.
SEEDS = {
    "net.gsantner.markor": SeedSpec(
        package="net.gsantner.markor",
        directory="/storage/emulated/0/Documents/markor",
    ),
    "com.amaze.filemanager": SeedSpec(
        package="com.amaze.filemanager",
        directory="/storage/emulated/0/Documents",
        # `DeleteTask.onPostExecute` indexes row 0 of an empty adapter; the
        # dataset's crash needs a directory that held exactly one item.
        only_item=True,
    ),
}


def seed_for(package: str) -> SeedSpec | None:
    """The seed spec for a build, or None when its path is not known."""
    return SEEDS.get(package)


def prepare(device, package: str) -> str:
    """Create the directory and one file, returning the path or a reason.

    Returns an empty string on success and a reason otherwise, so the caller
    can report "this build's data path is unknown" instead of running a task
    against an empty directory.
    """
    spec = seed_for(package)
    if spec is None:
        return f"no known data path for {package}"
    path = f"{spec.directory}/{spec.sample_file}"
    # A file written by the adb shell is owned by root and unreadable by the
    # app on older builds; the permission is part of seeding, not an
    # afterthought.
    device.shell(f"mkdir -p {spec.directory}")
    device.shell(f"printf '%s' '{spec.sample_text}' > {path}")
    device.shell(f"chmod 664 {path}")
    device.shell(f"chmod 775 {spec.directory}")
    if spec.only_item:
        # Leave nothing else behind: a delete that empties the directory is
        # the state several of these crashes need.
        device.shell(
            f"find {spec.directory} -mindepth 1 -maxdepth 1 "
            f"! -name '{spec.sample_file}' -exec rm -rf {{}} +"
        )
    listing = device.shell(f"ls {spec.directory}")
    if spec.sample_file not in listing:
        return f"seeded {path} but the directory does not list it"
    return ""


def as_record(package: str) -> dict:
    """The seed a run used, for the record."""
    spec = seed_for(package)
    if spec is None:
        return {"package": package, "seeded": False, "reason": "unknown path"}
    return {
        "package": package,
        "seeded": True,
        "directory": spec.directory,
        "file": spec.sample_file,
    }
