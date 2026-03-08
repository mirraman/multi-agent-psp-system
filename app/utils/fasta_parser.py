"""
Utilities for parsing FASTA-format files or strings.

A FASTA file looks like:
    >protein_1 optional description
    MKTLLILALAL...
    >protein_2
    AGSTKDL...
"""
from __future__ import annotations

import re
from typing import List, Tuple


def parse_fasta(content: str) -> List[Tuple[str, str, str]]:
    """
    Parse a FASTA string (or file content) into a list of proteins.

    Returns
    -------
    List of (header, name, sequence) tuples where:
        - header  = full header line without the leading '>'
        - name    = first word of the header (the identifier)
        - sequence = upper-cased amino-acid string with whitespace removed
    """
    entries: List[Tuple[str, str, str]] = []
    current_header: str | None = None
    current_seq_parts: List[str] = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_header is not None:
                seq = "".join(current_seq_parts).upper()
                if seq:
                    name = current_header.split()[0]
                    entries.append((current_header, name, seq))
            current_header = line[1:].strip()
            current_seq_parts = []
        else:
            # Remove any non-amino-acid characters (digits, spaces, *)
            clean = re.sub(r"[^A-Za-z]", "", line)
            current_seq_parts.append(clean)

    # Don't forget the last entry
    if current_header is not None:
        seq = "".join(current_seq_parts).upper()
        if seq:
            name = current_header.split()[0]
            entries.append((current_header, name, seq))

    return entries


def is_valid_protein_sequence(sequence: str) -> bool:
    """Return True if the string looks like a valid amino acid sequence."""
    valid_aa = set("ACDEFGHIKLMNPQRSTVWYBZXU")
    return bool(sequence) and all(c in valid_aa for c in sequence.upper())
