import unittest

from scripts.import_book import choose_import_review_state


class ImportReviewStateTests(unittest.TestCase):
    def test_default_new_book_is_pending_review(self):
        state = choose_import_review_state(existing_book=None, fingerprint_book=None)
        self.assertEqual(state.get("toc_review_status"), "pending_review")
        self.assertTrue(bool(state.get("review_required")))
        self.assertEqual(state.get("review_state_origin"), "default_pending_new_book")

    def test_existing_approved_is_reused(self):
        state = choose_import_review_state(
            existing_book={
                "book_id": "book-a",
                "book_fingerprint": "abc",
                "toc_review_status": "approved",
                "toc_reviewed_at": "2026-04-01T00:00:00+00:00",
            },
            fingerprint_book=None,
        )
        self.assertEqual(state.get("toc_review_status"), "approved")
        self.assertFalse(bool(state.get("review_required")))
        self.assertEqual(state.get("review_state_origin"), "existing_book_id_approved_reused")
        self.assertEqual(state.get("inherited_from_book_id"), "book-a")
        self.assertEqual(state.get("inherited_from_fingerprint"), "abc")

    def test_existing_rejected_requires_rereview(self):
        state = choose_import_review_state(
            existing_book={
                "book_id": "book-a",
                "toc_review_status": "rejected",
                "book_fingerprint": "abc",
            },
            fingerprint_book=None,
        )
        self.assertEqual(state.get("toc_review_status"), "pending_review")
        self.assertTrue(bool(state.get("review_required")))
        self.assertEqual(state.get("review_state_origin"), "existing_book_id_rejected_requires_rereview")

    def test_fingerprint_approved_is_inherited_for_new_book_id(self):
        state = choose_import_review_state(
            existing_book=None,
            fingerprint_book={
                "book_id": "book-old",
                "book_fingerprint": "fp-1",
                "toc_review_status": "approved",
                "toc_reviewed_at": "2026-03-01T00:00:00+00:00",
            },
        )
        self.assertEqual(state.get("toc_review_status"), "approved")
        self.assertFalse(bool(state.get("review_required")))
        self.assertEqual(state.get("review_state_origin"), "fingerprint_match_approved_reused")
        self.assertEqual(state.get("inherited_from_book_id"), "book-old")
        self.assertEqual(state.get("inherited_from_fingerprint"), "fp-1")


if __name__ == "__main__":
    unittest.main()
