fake_stream_1: fake_stream_1.stamp

fake_stream_1.stamp: fake_stream_1.patch
	rm -rf fake_stream_1
	cp -a fake_stream_0 fake_stream_1
	patch -p1 -dfake_stream_1 < fake_stream_1.patch
	touch fake_stream_1.stamp

clean:
	rm -Rf fake_stream_1 fake_stream_1.stamp

.PHONY: clean fake_stream_1
