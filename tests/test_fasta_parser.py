from app.utils.fasta_parser import is_valid_protein_sequence, parse_fasta


def test_parse_fasta_single_entry():
    raw = """>sp|P12345|TEST
MKTAYIAKQR"""
    entries = parse_fasta(raw)
    assert len(entries) == 1
    header, name, seq = entries[0]
    assert "P12345" in header
    assert name == "sp|P12345|TEST"
    assert seq == "MKTAYIAKQR"


def test_parse_fasta_strips_whitespace_and_digits():
    raw = """>p1 desc
MKTA 123
YIAK"""
    _, _, seq = parse_fasta(raw)[0]
    assert seq == "MKTAYIAK"


def test_is_valid_protein_sequence():
    assert is_valid_protein_sequence("ACDEFGHIKLMNPQRSTVWY")
    assert not is_valid_protein_sequence("")
    assert not is_valid_protein_sequence("AC0")
