from .schemas import Book
from common.pipeline import step

@step("assemble_book")
def assemble_book(native: list[Page], ocr: list[Page],
                   decisions: list[PageDecision], profile: BookProfile) -> Book:
    all_pages = sorted(native + ocr, key=lambda p: p.page_num)
    return Book(profile_name=profile.name, pages=all_pages, decisions=decisions)