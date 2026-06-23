"""Code shell-script style detection tests.

A new CodeFields.shell_style slot tags the shell dialect a shell
snippet is using: ``bash`` / ``zsh`` / ``fish`` / ``powershell`` /
``tcsh`` / ``posix``.

Returns ``None`` when the snippet's language is not in the shell
family OR when the snippet is empty / pure-comments.

Detection precedence (most-specific-first):

1. PowerShell  -- cmdlet vocabulary + operator syntax
2. fish        -- set-x assignment + string builtin
3. tcsh / csh  -- set= / setenv / foreach
4. zsh         -- glob qualifiers / autoload / zstyle
5. bash        -- [[ ]] / process-sub / ANSI quoting / arrays
6. posix       -- shell snippet with NONE of the above signals
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_shell_style, enrich_code

# ---- PowerShell signals ------------------------------------------


def test_powershell_get_cmdlet():
    out = detect_shell_style("Get-Process | Where-Object {$_.CPU -gt 10}", "powershell")
    assert out == "powershell"


def test_powershell_set_cmdlet():
    out = detect_shell_style("Set-Location $HOME", "powershell")
    assert out == "powershell"


def test_powershell_invoke_cmdlet():
    out = detect_shell_style("Invoke-WebRequest -Uri https://example.com", "powershell")
    assert out == "powershell"


def test_powershell_eq_operator():
    out = detect_shell_style("if ($x -eq 5) { Write-Host 'match' }", "powershell")
    assert out == "powershell"


def test_powershell_cmdletbinding():
    text = "[CmdletBinding()]\nparam($foo)"
    out = detect_shell_style(text, "powershell")
    assert out == "powershell"


def test_powershell_parameter_attribute():
    text = "[Parameter(Mandatory)] [string] $Name"
    out = detect_shell_style(text, "powershell")
    assert out == "powershell"


def test_powershell_psitem_pipeline():
    out = detect_shell_style("$obj | ForEach-Object { $_.Name }", "powershell")
    assert out == "powershell"


def test_powershell_psitem_explicit():
    out = detect_shell_style("$results | Where { $PSItem.Status -eq 'OK' }", "powershell")
    assert out == "powershell"


def test_powershell_type_accelerator():
    out = detect_shell_style("[int] $n = 5", "powershell")
    assert out == "powershell"


def test_powershell_write_host():
    out = detect_shell_style("Write-Host 'hello world'", "powershell")
    assert out == "powershell"


def test_powershell_alias_ps1():
    out = detect_shell_style("Get-Service | Stop-Service", "ps1")
    assert out == "powershell"


def test_powershell_alias_pwsh():
    out = detect_shell_style("Set-Location /tmp", "pwsh")
    assert out == "powershell"


# ---- fish signals ------------------------------------------------


def test_fish_set_x():
    out = detect_shell_style("set -x PATH /usr/local/bin $PATH", "fish")
    assert out == "fish"


def test_fish_set_no_dash():
    out = detect_shell_style("set MYVAR hello", "fish")
    assert out == "fish"


def test_fish_string_match():
    out = detect_shell_style("string match -r '^foo' bar", "fish")
    assert out == "fish"


def test_fish_string_sub():
    out = detect_shell_style("string sub -s 1 -l 3 hello", "fish")
    assert out == "fish"


def test_fish_function_argument_names():
    out = detect_shell_style(
        "function greet --argument-names name\n    echo hi $name\nend",
        "fish",
    )
    assert out == "fish"


def test_fish_commandline_builtin():
    out = detect_shell_style("commandline -f execute", "fish")
    assert out == "fish"


def test_fish_status_is_interactive():
    out = detect_shell_style("if status is-interactive\n    echo hi\nend", "fish")
    assert out == "fish"


def test_fish_functions_query():
    out = detect_shell_style("functions -q my_func", "fish")
    assert out == "fish"


# ---- tcsh / csh signals ------------------------------------------


def test_tcsh_set_with_equals():
    out = detect_shell_style("set foo = bar", "tcsh")
    assert out == "tcsh"


def test_tcsh_setenv():
    out = detect_shell_style("setenv PATH /usr/local/bin", "tcsh")
    assert out == "tcsh"


def test_tcsh_foreach():
    out = detect_shell_style(
        "foreach i (1 2 3)\n    echo $i\nend",
        "tcsh",
    )
    assert out == "tcsh"


def test_tcsh_if_paren_then():
    text = "if ($foo == bar) then\n    echo match\nendif"
    out = detect_shell_style(text, "tcsh")
    assert out == "tcsh"


def test_tcsh_alias_quote():
    out = detect_shell_style("alias ll 'ls -la'", "tcsh")
    assert out == "tcsh"


def test_csh_alias_recognised_as_tcsh():
    out = detect_shell_style("setenv FOO bar", "csh")
    assert out == "tcsh"


# ---- zsh signals -------------------------------------------------


def test_zsh_glob_qualifier_dot():
    out = detect_shell_style("ls *.txt(.om[1])", "zsh")
    assert out == "zsh"


def test_zsh_param_flag():
    out = detect_shell_style('echo ${(U)foo}', "zsh")
    assert out == "zsh"


def test_zsh_autoload():
    out = detect_shell_style("autoload -Uz compinit", "zsh")
    assert out == "zsh"


def test_zsh_prompt_color():
    out = detect_shell_style("PROMPT='%F{red}>%f '", "zsh")
    assert out == "zsh"


def test_zsh_zmodload():
    out = detect_shell_style("zmodload zsh/datetime", "zsh")
    assert out == "zsh"


def test_zsh_zstyle():
    out = detect_shell_style("zstyle ':completion:*' menu select", "zsh")
    assert out == "zsh"


# ---- bash signals ------------------------------------------------


def test_bash_double_brackets():
    out = detect_shell_style("if [[ $x == 'foo' ]]; then echo yes; fi", "bash")
    assert out == "bash"


def test_bash_process_substitution():
    out = detect_shell_style("diff <(sort a) <(sort b)", "bash")
    assert out == "bash"


def test_bash_array_assignment():
    out = detect_shell_style("arr=(a b c)\necho ${arr[0]}", "bash")
    assert out == "bash"


def test_bash_ansi_c_quoting():
    out = detect_shell_style("echo $'\\thello\\n'", "bash")
    assert out == "bash"


def test_bash_regex_match_operator():
    out = detect_shell_style("if [[ $x =~ ^[0-9]+$ ]]; then echo num; fi", "bash")
    assert out == "bash"


def test_bash_function_keyword():
    out = detect_shell_style("function my_func {\n    echo hi\n}", "bash")
    assert out == "bash"


def test_bash_declare_a():
    out = detect_shell_style("declare -a arr\narr+=(item)", "bash")
    assert out == "bash"


def test_bash_local_n_nameref():
    out = detect_shell_style("local -n ref=var", "bash")
    assert out == "bash"


def test_bash_brace_expansion_range():
    out = detect_shell_style("for i in {1..10}; do echo $i; done", "bash")
    assert out == "bash"


def test_bash_mapfile():
    out = detect_shell_style("mapfile -t lines < file.txt", "bash")
    assert out == "bash"


def test_bash_readarray():
    out = detect_shell_style("readarray -t arr < input", "bash")
    assert out == "bash"


def test_bash_alias_sh():
    """A snippet tagged ``sh`` with bash-isms tags as bash."""
    out = detect_shell_style("if [[ -f file.txt ]]; then cat file.txt; fi", "sh")
    assert out == "bash"


# ---- POSIX fallback ----------------------------------------------


def test_posix_basic_sh():
    out = detect_shell_style("ls -la /tmp\nfoo=bar\necho hi", "sh")
    assert out == "posix"


def test_posix_single_bracket_test():
    """``[ -f file ]`` (single bracket) is POSIX-compliant."""
    out = detect_shell_style("if [ -f /etc/hosts ]; then cat /etc/hosts; fi", "sh")
    assert out == "posix"


def test_posix_function_paren_form():
    """``foo() { ... }`` (paren form, no function keyword) is POSIX."""
    out = detect_shell_style("my_func() {\n    echo hi\n}", "sh")
    assert out == "posix"


def test_posix_shell_language_no_signals():
    """Language tagged ``shell`` with no signals returns posix."""
    out = detect_shell_style("echo hello\nls /tmp", "shell")
    assert out == "posix"


def test_posix_ksh_language_no_signals():
    """Language tagged ``ksh`` with no signals returns posix."""
    out = detect_shell_style("echo hello", "ksh")
    assert out == "posix"


def test_posix_bash_language_no_bash_signals():
    """Language tagged ``bash`` but no bash signals -> posix."""
    out = detect_shell_style("echo hello\nls /tmp", "bash")
    assert out == "posix"


# ---- Non-shell languages return None -----------------------------


def test_python_returns_none():
    out = detect_shell_style("def foo():\n    return 42", "python")
    assert out is None


def test_javascript_returns_none():
    out = detect_shell_style("const x = 5;", "javascript")
    assert out is None


def test_go_returns_none():
    out = detect_shell_style("package main\nfunc main() {}", "go")
    assert out is None


def test_yaml_returns_none():
    out = detect_shell_style("foo: bar\nbaz: qux", "yaml")
    assert out is None


def test_python_with_shell_lookalike_text():
    """Python snippet containing what LOOKS like bash syntax in a
    string still returns None because language gate enforced."""
    out = detect_shell_style("x = '[[ $foo ]]'", "python")
    assert out is None


# ---- Empty / null inputs -----------------------------------------


def test_empty_string_returns_none():
    assert detect_shell_style("", "bash") is None


def test_whitespace_only_returns_none():
    assert detect_shell_style("   \n   \n", "bash") is None


def test_no_language_no_signals_returns_none():
    """When language is None AND no shell signals are present,
    return None (don't false-positive on JSON / YAML / etc)."""
    out = detect_shell_style("foo: bar\nbaz: qux", None)
    assert out is None


def test_no_language_with_bash_signal_returns_bash():
    """When language is None but bash signal IS present, we
    confidently return bash (the [[ ]] form is unmistakable)."""
    out = detect_shell_style("if [[ $x = foo ]]; then echo yes; fi", None)
    assert out == "bash"


def test_no_language_with_powershell_signal_returns_powershell():
    """Language unknown + PS signal -> powershell."""
    out = detect_shell_style("Get-Process | Where-Object Status -eq Running", None)
    assert out == "powershell"


# ---- Precedence: PowerShell wins -----------------------------------


def test_powershell_wins_over_bash_signal():
    """If both PowerShell and bash signals are present, PowerShell
    wins (precedence-based detection)."""
    text = "Get-Process\nif [[ $x ]]; then echo yes; fi"
    out = detect_shell_style(text, "powershell")
    assert out == "powershell"


def test_fish_wins_over_bash_signal():
    """fish ``set -x`` wins over a bash ``[[ ]]`` reference."""
    text = "set -x PATH /usr/bin\nif [[ -f file ]]; then echo yes; fi"
    out = detect_shell_style(text, "fish")
    assert out == "fish"


def test_zsh_wins_over_bash_signal():
    """zsh-specific signals win over bash signals."""
    text = "autoload -Uz compinit\nif [[ -f file ]]; then echo yes; fi"
    out = detect_shell_style(text, "zsh")
    assert out == "zsh"


# ---- Realistic content fixtures ----------------------------------


def test_realistic_bash_function_with_args():
    text = """#!/bin/bash
set -e

deploy() {
    local env="$1"
    if [[ -z "$env" ]]; then
        echo "usage: deploy <env>" >&2
        return 1
    fi
    docker build -t app:$(git rev-parse HEAD) .
    kubectl apply -f deploy-$env.yaml
}

deploy "$@"
"""
    out = detect_shell_style(text, "bash")
    assert out == "bash"


def test_realistic_zsh_oh_my_zsh_config():
    text = """# Oh-my-zsh setup
zstyle ':completion:*' menu select
autoload -Uz compinit && compinit

PROMPT='%F{green}%n@%m%f:%F{blue}%~%f$ '
"""
    out = detect_shell_style(text, "zsh")
    assert out == "zsh"


def test_realistic_fish_config():
    text = """# Fish config
set -x EDITOR vim
set -x PATH /usr/local/bin $PATH

function gco --argument-names branch
    git checkout $branch
end

if status is-interactive
    fish_vi_key_bindings
end
"""
    out = detect_shell_style(text, "fish")
    assert out == "fish"


def test_realistic_powershell_module():
    text = """function Get-MyData {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Name
    )

    $results = Invoke-WebRequest -Uri "https://api.example.com/$Name"
    if ($results.StatusCode -eq 200) {
        Write-Host "Got $($results.Content.Length) bytes"
    }
}

Get-MyData -Name 'foo'
"""
    out = detect_shell_style(text, "powershell")
    assert out == "powershell"


def test_realistic_posix_install_script():
    """A portable install script with no bash-isms."""
    text = """#!/bin/sh
set -e

INSTALL_DIR=/usr/local
if [ ! -d "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
fi

cp ./bin/* "$INSTALL_DIR/bin/"
echo "Installed to $INSTALL_DIR"
"""
    out = detect_shell_style(text, "sh")
    assert out == "posix"


def test_realistic_tcsh_old_config():
    text = """# .tcshrc
set path = ( $path /usr/local/bin )
setenv EDITOR vim

alias ll 'ls -la'
alias gst 'git status'

foreach pkg ( vim git tmux )
    which $pkg
end
"""
    out = detect_shell_style(text, "tcsh")
    assert out == "tcsh"


# ---- enrich_code integration --------------------------------------


def test_enrich_code_populates_shell_style_bash():
    text = "if [[ -f /etc/hosts ]]; then cat /etc/hosts; fi"
    fields = enrich_code(None, OCRResult(text=text))
    # detect_language may tag this as bash/sh/shell
    if fields.language and fields.language.lower() in {"bash", "sh", "shell"}:
        assert fields.shell_style == "bash"


def test_enrich_code_python_has_none_shell_style():
    text = "def hello():\n    print('world')"
    fields = enrich_code(None, OCRResult(text=text))
    assert fields.shell_style is None


def test_enrich_code_preserves_caller_shell_style():
    existing = CodeFields(language="bash", code="echo hi", shell_style="bash")
    fields = enrich_code(existing, OCRResult(text="echo hi"))
    assert fields.shell_style == "bash"


def test_enrich_code_javascript_returns_none_shell_style():
    text = "const greet = name => `hello ${name}`;"
    fields = enrich_code(None, OCRResult(text=text))
    assert fields.shell_style is None
