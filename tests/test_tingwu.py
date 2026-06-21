from douyin_transcribe.transcribers.tingwu import transcript_from_tingwu_result


def test_transcript_from_tingwu_sentence_result():
    result = {
        "Transcription": {
            "Paragraphs": [
                {
                    "Sentences": [
                        {"BeginTime": 0, "EndTime": 1200, "Text": "第一句"},
                        {"BeginTime": 1200, "EndTime": 2600, "Text": "第二句"},
                    ]
                }
            ]
        }
    }

    transcript = transcript_from_tingwu_result(result)

    assert transcript.engine == "tingwu"
    assert transcript.text == "第一句\n第二句"
    assert [item.text for item in transcript.segments] == ["第一句", "第二句"]


def test_transcript_merges_word_level_result():
    result = {
        "Transcription": {
            "Words": [
                {"BeginTime": 0, "EndTime": 200, "Text": "至少"},
                {"BeginTime": 200, "EndTime": 900, "Text": "3000家以上"},
                {"BeginTime": 900, "EndTime": 1200, "Text": "上涨"},
                {"BeginTime": 1200, "EndTime": 1400, "Text": "才"},
                {"BeginTime": 1400, "EndTime": 1800, "Text": "做"},
                {"BeginTime": 1800, "EndTime": 2200, "Text": "买入"},
                {"BeginTime": 2200, "EndTime": 2600, "Text": "交易。"},
            ]
        }
    }

    transcript = transcript_from_tingwu_result(result)

    assert transcript.text == "至少3000家以上上涨才做买入交易。"
    assert len(transcript.segments) == 1
