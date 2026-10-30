"""Compile vetted LaTeX to a PNG inside a network-less, read-only Bubblewrap."""
import os
import subprocess
import tempfile
from pathlib import Path

from guardrails import latex_reason

TEMPLATE=r'''\documentclass[border=16pt,varwidth=620pt]{standalone}
\usepackage{amsmath,amssymb,mathtools}
\usepackage[fontset=none]{ctex}
\setCJKmainfont{Noto Serif CJK SC}
\setmainfont{Latin Modern Roman}
\begin{document}
%s
\end{document}
'''
BWRAP=['/usr/bin/bwrap','--die-with-parent','--new-session','--unshare-all','--cap-drop','ALL',
       '--ro-bind','/usr','/usr','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib',
       '--symlink','usr/lib64','/lib64','--ro-bind','/etc/texmf','/etc/texmf','--ro-bind','/etc/fonts','/etc/fonts',
       '--ro-bind','/etc/alternatives','/etc/alternatives','--ro-bind','/var/lib/texmf','/var/lib/texmf',
       '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--tmpfs','/home/tex','--clearenv',
       '--setenv','PATH','/usr/bin:/bin','--setenv','HOME','/home/tex','--setenv','openin_any','p',
       '--setenv','openout_any','p','--setenv','TEXMFVAR','/tmp','--setenv','TEXMFCONFIG','/tmp',
       '--setenv','TEXMFOUTPUT','/work','--setenv','LANG','C.UTF-8']


def render(body,dpi=190):
    """Return PNG bytes, or raise RuntimeError. Output is bounded."""
    if latex_reason(body):raise RuntimeError('LATEX_REJECTED')
    with tempfile.TemporaryDirectory(prefix='tex-') as work:
        Path(work,'a.tex').write_text(TEMPLATE%body,encoding='utf-8')
        # Recoverable LaTeX errors still yield a PDF; only a missing PDF counts as failure.
        script=('timeout 40 xelatex -no-shell-escape -interaction=nonstopmode -output-directory=/work a.tex >/dev/null 2>&1; '
                'test -s a.pdf || { grep -m1 "^!" a.log; exit 1; }; '
                'timeout 20 pdftoppm -png -r %d -singlefile -f 1 -l 1 a.pdf out'%dpi)
        command=BWRAP+['--bind',work,'/work','--chdir','/work','--','/bin/sh','-c',script]
        try:
            done=subprocess.run(command,timeout=70,stdin=subprocess.DEVNULL,capture_output=True,text=True,
                                env={'PATH':'/usr/bin:/bin'})
        except (subprocess.SubprocessError,OSError):
            raise RuntimeError('LATEX_COMPILE_FAILED') from None
        if done.returncode:
            raise RuntimeError('LATEX_COMPILE_FAILED: '+done.stdout.strip()[:120])
        png=Path(work,'out.png')
        if not png.is_file() or not 200<png.stat().st_size<=3_000_000:raise RuntimeError('LATEX_OUTPUT_INVALID')
        return png.read_bytes()
