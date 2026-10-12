import React, { useRef, useState } from 'react';
import { UploadCloud, CheckCircle, AlertCircle, FileText } from 'lucide-react';
import { api } from '../services/api';

const FileUpload = ({
  onUploadSuccess,
  userId = 'test_user_01',
  compact = false,
}) => {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState('idle');
  const [message, setMessage] = useState('');
  const fileInputRef = useRef(null);

  const resetFileInput = () => {
    setFile(null);

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];

    if (selectedFile) {
      setFile(selectedFile);
      setStatus('idle');
      setMessage('');
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setStatus('uploading');
    setMessage('');

    try {
      const response = await api.uploadDocument(file, userId);

      setStatus('success');
      setMessage(response.message || 'Document processed successfully.');

      resetFileInput();

      if (onUploadSuccess) {
        onUploadSuccess(response);
      }
    } catch (error) {
      console.error(error);

      if (error.status === 409) {
        setStatus('duplicate');
        setMessage('This document is already uploaded. You can select it from uploaded documents.');

        resetFileInput();

        if (onUploadSuccess) {
          onUploadSuccess(error);
        }

        return;
      }

      setStatus('error');
      setMessage(error.message || 'Upload failed. Please check backend console.');
    }
  };

  const getStatusBox = () => {
    if (status === 'success') {
      return (
        <div className="status-box success">
          <CheckCircle size={22} />
          <div>
            <h3>Document Processed Successfully</h3>
            <p>{message}</p>
          </div>
        </div>
      );
    }

    if (status === 'duplicate') {
      return (
        <div className="status-box warning">
          <AlertCircle size={22} />
          <div>
            <h3>Duplicate Document</h3>
            <p>{message}</p>
          </div>
        </div>
      );
    }

    if (status === 'error') {
      return (
        <div className="status-box error">
          <AlertCircle size={22} />
          <div>
            <h3>Upload Failed</h3>
            <p>{message}</p>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <section className={compact ? 'upload-card compact-upload' : 'panel-card upload-card'}>
      {!compact && (
        <>
          <div className="upload-icon">
            <UploadCloud size={36} />
          </div>

          <h3>Upload PDF Document</h3>

          <p className="upload-description">
            Upload your document. Krish AI will read it and answer only from the selected PDF.
          </p>
        </>
      )}

      {compact && (
        <div className="compact-upload-title">
          <UploadCloud size={28} />
          <div>
            <h3>Choose your PDF</h3>
            <p>Only PDF files are supported.</p>
          </div>
        </div>
      )}

      <div className="file-row">
        <label className="file-picker">
          <FileText size={18} />
          <span>{file ? file.name : 'Choose PDF file'}</span>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            onChange={handleFileChange}
          />
        </label>

        <button
          onClick={handleUpload}
          disabled={!file || status === 'uploading'}
          className="primary-action-small"
        >
          {status === 'uploading' ? 'Processing...' : 'Upload & Train AI'}
        </button>
      </div>

      {getStatusBox()}
    </section>
  );
};

export default FileUpload;