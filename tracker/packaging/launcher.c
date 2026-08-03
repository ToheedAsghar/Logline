/*
 * Main executable of LoglineTracker.app.
 *
 * This exists so the tracker has a stable identity for macOS's Accessibility (TCC)
 * grant. It has to be a compiled Mach-O binary, not a shell script: with a script as
 * the bundle's main executable, `codesign` reports "app bundle with generic" and the
 * process macOS actually launches is /bin/bash — a platform binary with its own code
 * identity — so TCC has nothing belonging to this bundle to attribute the grant to,
 * and every Accessibility call comes back kAXErrorAPIDisabled. A Mach-O executable
 * carries the bundle's signature, and the Python child inherits it as the responsible
 * process, exactly as a script launched from a granted terminal inherits the
 * terminal's grant.
 *
 * This file deliberately contains NO machine-specific paths, because macOS pins the
 * grant to the bundle's code signature: anything that varies per machine, per repo
 * location, or per Python version would change the signed bytes and cost the grant.
 * Those values live in the config file below, outside the bundle, so Python upgrades,
 * venv rebuilds, and repo moves are all free.
 *
 * Config file format (shell-style assignments):
 *     REPO_ROOT=/Users/you/Documents/projects/logline
 */

#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define EX_CONFIG 78

static const char *CONFIG_RELATIVE = "Library/Application Support/Logline/tracker.env";
static const char *PYTHON_RELATIVE = "tracker/.venv/bin/python";
static const char *DEFAULT_MODULE = "tracker.main";

static volatile sig_atomic_t child_pid = 0;

/* Pass termination on to the tracker so its shutdown path runs and seals the open
 * session, instead of leaving a dangling one for the next start to recover. */
static void forward_signal(int signo)
{
    if (child_pid > 0) {
        kill(child_pid, signo);
    }
}

static int read_repo_root(const char *path, char *out, size_t out_len)
{
    FILE *file = fopen(path, "r");
    if (file == NULL) {
        return -1;
    }

    char line[PATH_MAX + 64];
    int found = -1;

    while (fgets(line, sizeof line, file) != NULL) {
        char *value = line;
        while (*value == ' ' || *value == '\t') {
            value++;
        }
        if (strncmp(value, "REPO_ROOT=", 10) != 0) {
            continue;
        }
        value += 10;

        size_t len = strlen(value);
        while (len > 0 && (value[len - 1] == '\n' || value[len - 1] == '\r' ||
                           value[len - 1] == ' ' || value[len - 1] == '\t')) {
            value[--len] = '\0';
        }
        if (len >= 2 && ((value[0] == '"' && value[len - 1] == '"') ||
                         (value[0] == '\'' && value[len - 1] == '\''))) {
            value[len - 1] = '\0';
            value++;
            len -= 2;
        }
        if (len == 0 || len >= out_len) {
            break;
        }
        memcpy(out, value, len + 1);
        found = 0;
        break;
    }

    fclose(file);
    return found;
}

int main(void)
{
    const char *home = getenv("HOME");
    if (home == NULL || *home == '\0') {
        fprintf(stderr, "logline-tracker: HOME is not set\n");
        return EX_CONFIG;
    }

    char config[PATH_MAX];
    if (snprintf(config, sizeof config, "%s/%s", home, CONFIG_RELATIVE) >= (int)sizeof config) {
        fprintf(stderr, "logline-tracker: config path too long\n");
        return EX_CONFIG;
    }

    char repo_root[PATH_MAX];
    if (read_repo_root(config, repo_root, sizeof repo_root) != 0) {
        fprintf(stderr, "logline-tracker: no readable REPO_ROOT in %s\n", config);
        return EX_CONFIG;
    }

    char python[PATH_MAX];
    if (snprintf(python, sizeof python, "%s/%s", repo_root, PYTHON_RELATIVE) >= (int)sizeof python) {
        fprintf(stderr, "logline-tracker: python path too long\n");
        return EX_CONFIG;
    }
    if (access(python, X_OK) != 0) {
        fprintf(stderr, "logline-tracker: no tracker venv at %s (see tracker/README.md)\n", python);
        return EX_CONFIG;
    }

    if (chdir(repo_root) != 0) {
        fprintf(stderr, "logline-tracker: cannot enter %s: %s\n", repo_root, strerror(errno));
        return EX_CONFIG;
    }

    const char *module = getenv("LOGLINE_TRACKER_MODULE");
    if (module == NULL || *module == '\0') {
        module = DEFAULT_MODULE;
    }

    /* Installed before the fork so a signal arriving immediately after it is still
     * forwarded; exec resets handlers to default in the child. */
    signal(SIGTERM, forward_signal);
    signal(SIGINT, forward_signal);

    pid_t pid = fork();
    if (pid < 0) {
        fprintf(stderr, "logline-tracker: fork failed: %s\n", strerror(errno));
        return 1;
    }

    if (pid == 0) {
        char *argv[] = {python, "-m", (char *)module, NULL};
        execv(python, argv);
        fprintf(stderr, "logline-tracker: cannot exec %s: %s\n", python, strerror(errno));
        _exit(127);
    }

    child_pid = pid;

    int status = 0;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) {
            fprintf(stderr, "logline-tracker: waitpid failed: %s\n", strerror(errno));
            return 1;
        }
    }

    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }
    return 1;
}
