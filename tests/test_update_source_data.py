from municipal_finances.update_source_data import main

# todo fix this test


def test_main(mocker):
    mock_get_fir_data = mocker.Mock()
    mocker.patch("muni_hospital.update_source_data.get_fir_data", mock_get_fir_data)

    main()

    mock_get_fir_data.assert_called_once()
